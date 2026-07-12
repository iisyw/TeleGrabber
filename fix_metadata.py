#!/usr/bin/env python3
"""
回填/修复历史记录的 message_time、message_id、source_link。

数据流程：5 个 Phase 层层递进
  Phase 1: source_link 已有 /msg_id → Pyrogram 直接取消息时间
  Phase 2: source_link 末尾提取 msg_id（纯 SQL）
  Phase 3: source_link 补上 /msg_id 后缀
  Phase 4: 扫你↔Bot 聊天记录，按 file_unique_id 匹配（视频/文档）
  Phase 5: 扫你↔Bot 聊天记录，按 file_size 匹配（照片，编码差异绕过）
"""
import asyncio
import re
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config
from utils import DB_PATH, _db_lock, utc_to_local


# ── 辅助函数 ──────────────────────────────────────────────────────────

def parse_source_link(source_link):
    """
    从 source_link 提取 (chat_id, msg_id)。

    source_link 有两种格式：
      格式 A: https://t.me/sifangktv10/12345   → 用户名频道 + msg_id
      格式 B: https://t.me/c/1812716119/12345   → 数字 ID 频道 + msg_id
        注意: Telegram 内部频道 ID 是 -100xxxxxxxxx,
              source_link 里存的是去掉 -100 后的纯数字

    返回:
      (chat_id, msg_id)  或  None
        chat_id: 整数（格式B）或字符串用户名（格式A）
        msg_id:  整数
    """
    # 先试格式 B: t.me/c/xxxx/yyyy
    m = re.match(r'https://t\.me/c/(-?\d+)/(\d+)', source_link or '')
    if m:
        raw = int(m.group(1))          # 提取去掉 -100 的频道 ID
        # 还原为完整 ID：正数 → 加 -100 前缀；负数（极少情况）直接使用
        chat_id = raw if raw < 0 else -1000000000000 - raw
        return chat_id, int(m.group(2))  # (完整chat_id, msg_id)

    # 再试格式 A: t.me/username/yyyy
    m = re.match(r'https://t\.me/([^/]+)/(\d+)', source_link or '')
    if m and m.group(1) != 'c':        # 排除前面格式 B 的误匹配
        return m.group(1), int(m.group(2))  # (用户名字符串, msg_id)

    return None


def extract_msg_id_from_source_link(source_link):
    """
    只从 source_link 末尾提取 msg_id，不还原 chat_id。
    用于 Phase 2（纯 SQL，不需要 API 调用）。
    """
    m = re.match(r'https://t\.me/c/-?\d+/(\d+)$', source_link or '')
    if m:
        return int(m.group(1))
    m = re.match(r'https://t\.me/([^/]+)/(\d+)$', source_link or '')
    if m and m.group(1) != 'c':
        return int(m.group(2))
    return None


def get_db():
    """创建新数据库连接（线程安全调用方自己保证）。"""
    return __import__('sqlite3').connect(DB_PATH, timeout=60)


def update_record(record_id, **kwargs):
    """
    通用 UPDATE：SET k1=v1, k2=v2, ... WHERE id = record_id
    用 _db_lock 保证线程安全（backfill 单线程，但 utils.py 有锁）。
    """
    sets, vals = [], []
    for k, v in kwargs.items():
        sets.append(f"{k} = ?")
        vals.append(v)
    vals.append(record_id)
    with _db_lock:
        conn = get_db()
        try:
            conn.execute(f"UPDATE media_metadata SET {', '.join(sets)} WHERE id = ?", vals)
            conn.commit()
        finally:
            conn.close()


def _enum_value(v):
    """如果 v 是枚举类型，转成原始值。"""
    return v.value if hasattr(v, 'value') else v


async def _make_client():
    """创建 Pyrogram 用户客户端。"""
    from user_api import build_pyrogram_client
    return await build_pyrogram_client()


# ═══════════════════════════════════════════════════════════════════════
# Phase 1: 已有 /msg_id 的 source_link，直接从 API 获取
#
# 处理条件: message_time IS NULL 且 source_link 不为空
# 操作: 正则提取 chat_id + msg_id → Pyrogram get_messages → 回填
# ═══════════════════════════════════════════════════════════════════════

async def backfill_phase1():
    """
    从 source_link 中提取 (chat_id, msg_id)，
    用 Pyrogram 获取消息对象，回填 message_time、message_id、source_link。
    """
    # 查出所有缺 message_time 且有 source_link1 的记录
    with _db_lock:
        conn = get_db()
        try:
            rows = conn.execute(
                "SELECT id, source_link1 FROM media_metadata "
                "WHERE message_time IS NULL AND source_link1 != ''"
            ).fetchall()
        finally:
            conn.close()

    if not rows:
        print("Phase 1: 无待处理记录"); return

    print(f"Phase 1: {len(rows)} 条 — 从 source_link1 提取的 msg_id 获取 message_time")

    # 创建 Pyrogram 客户端（用你的用户账号访问频道）
    client = await _make_client()
    updated = 0

    for record_id, source_link1 in rows:
        # 从链接中提取 chat_id 和 msg_id
        parsed = parse_source_link(source_link1)
        if not parsed:          # 链接格式不匹配
            continue

        chat_id, msg_id = parsed

        try:
            # API 调用：获取原始消息
            msg = await client.get_messages(chat_id, msg_id)
            if msg is None:     # 消息不存在或用户账号不在频道里
                continue

            # 消息时间：UTC → 本地时间 → ISO 字符串
            msg_time = utc_to_local(msg.date).isoformat() if msg.date else None

            # 消息 ID：用 msg.id（我们按 source_link 的 msg_id 查到的就是这个消息本身）
            msg_id_val = msg.id

            # 重构 source_link1/source_link2（规范化，方便前端跳转）
            chat = msg.chat
            new_link1 = None
            new_link2 = None
            if chat:
                username = getattr(chat, 'username', None)
                cid = getattr(chat, 'id', None)
                link_msg_id = msg_id_val
                if username:
                    # 有用户名的频道：source_link1 用用户名格式，source_link2 用数字格式
                    new_link1 = f"https://t.me/{username}/{link_msg_id}"
                    new_link2 = f"https://t.me/c/{cid}/{link_msg_id}"
                elif cid:
                    # 无用户名的频道
                    new_link1 = f"https://t.me/c/{cid}/{link_msg_id}"
                    new_link2 = ''

            # 回填数据库
            update_record(record_id,
                message_time=msg_time,
                message_id=msg_id_val,
                source_link1=new_link1 or source_link1,
                source_link2=new_link2 or '',
                source_username=getattr(chat, 'username', None) if chat else '',
                source_type=_enum_value(getattr(chat, 'type', None)) if chat else '',
            )
            updated += 1

        except Exception as e:
            pass   # 忽略单条失败（如频道不可访问）

    await client.stop()
    print(f"Phase 1 完成: 更新 {updated} 条\n")


# ═══════════════════════════════════════════════════════════════════════
# Phase 2: 从 source_link 末尾提取 message_id（纯 SQL，零网络）
#
# 处理条件: message_id IS NULL 且 source_link 不为空
# 操作: 正则从链接末尾提取 /数字 → 直接 UPDATE
# ═══════════════════════════════════════════════════════════════════════

def backfill_phase2():
    """从 source_link 末尾提取 msg_id，纯 UPDATE 操作。"""
    with _db_lock:
        conn = get_db()
        rows = conn.execute(
            "SELECT id, source_link1 FROM media_metadata "
            "WHERE message_id IS NULL AND source_link1 != ''"
        ).fetchall()
        conn.close()

    updated = 0
    for record_id, source_link1 in rows:
        mid = extract_msg_id_from_source_link(source_link1)
        if mid is not None:
            update_record(record_id, message_id=mid)
            updated += 1

    print(f"Phase 2: 从 source_link 提取 message_id: {updated} 条\n")


# ═══════════════════════════════════════════════════════════════════════
# Phase 3: 频道记录的 source_link 补上 /msg_id
#
# 处理条件: source_type='channel' 且 message_id 已有值
#          且 source_link 末尾还没有 /数字
# 操作: source_link += "/" + message_id
# ═══════════════════════════════════════════════════════════════════════

def backfill_phase3():
    """
    Phase 1/2 后很多频道记录有了 message_id，但 source_link 还是裸链接：

      https://t.me/sifangktv10   ← 末尾没有 /12345

    加上去后前端才能直接跳转到原消息。
    """
    with _db_lock:
        conn = get_db()
        rows = conn.execute(
            "SELECT id, source_link1, source_link2, source_id, message_id, source_type "
            "FROM media_metadata "
            "WHERE source_type = 'channel' AND message_id IS NOT NULL AND (source_link1 != '' OR source_link2 != '')"
        ).fetchall()
        conn.close()

    updated = 0
    for record_id, source_link1, source_link2, source_id, msg_id, st in rows:
        # 如果 source_link1 末尾已有 /数字（如 t.me/xxx/123），跳过
        if source_link1 and re.search(r'/\d+$', source_link1):
            continue
        # 如果 source_link2 末尾已有 /数字，跳过
        if source_link2 and re.search(r'/\d+$', source_link2):
            continue

        # 构造新链接：原链接 + /message_id
        new_link1 = f"{source_link1}/{msg_id}" if source_link1 else ''
        new_link2 = f"{source_link2}/{msg_id}" if source_link2 else ''
        update_record(record_id, source_link1=new_link1, source_link2=new_link2)
        updated += 1

    print(f"Phase 3: source_link1/source_link2 追加 msg_id: {updated} 条\n")


# ═══════════════════════════════════════════════════════════════════════
# Phase 4: 扫描你↔Bot 聊天记录（file_unique_id + file_size 双重匹配）
#
# 背景:
#   你↔Bot 的聊天记录里每个转发都包含原始消息的 ID 和时间。
#   一次扫描用两种方法匹配所有类型的媒体：
#     - file_unique_id: 精准，视频/文档用（两套 API 编码一致）
#     - (source_id, file_size): 照片用（两套 API 编码不同，但文件大小一致）
# ═══════════════════════════════════════════════════════════════════════

async def backfill_phase4():
    """
    一次扫描你↔Bot 聊天记录，用两种策略匹配所有待回填记录：
      1. file_unique_id（视频/文档）
      2. (source_id, file_size)（照片，先通过 Bot API getFile 拿大小）
    """
    import socks, socket, urllib.request, json
    from collections import defaultdict

    # ── 读数据库：所有缺 message_id 的记录 ──
    with _db_lock:
        conn = get_db()
        rows = conn.execute(
            "SELECT id, source_id, file_id, file_unique_id, source_name "
            "FROM media_metadata "
            "WHERE message_id IS NULL AND file_unique_id != ''"
        ).fetchall()
        conn.close()

    if not rows:
        print("Phase 4: 无待处理记录"); return

    total = len(rows)

    # ── 构建 file_unique_id 匹配索引（精准匹配）──
    # 可以匹配的: 视频/文档等（file_unique_id 两套 API 编码一致）
    fuid_lookup = {}  # file_unique_id → (rid, source_name)
    # 需要 file_size 匹配的: 照片 AQAD 前缀（编码不同）
    fs_need = []      # [(rid, source_id, file_id)]
    for rid, sid, fid, fuid, sname in rows:
        if fuid.startswith(('AQAD', 'AQAE')):
            fs_need.append((rid, sid, fid))
        else:
            fuid_lookup[fuid] = (rid, sname)

    # ── Bot API getFile 拿照片的 file_size（并发）──
    rid_to_fs = {}
    rid_to_sid = {}
    rid_to_sname = {}
    if fs_need:
        import concurrent.futures
        socks.setdefaultproxy(socks.PROXY_TYPE_SOCKS5, '127.0.0.1', 10808)
        socket.socket = socks.socksocket
        print(f"Phase 4: Bot API getFile 获取 {len(fs_need)} 条照片 file_size（并发 10）...")
        with _db_lock:
            c2 = get_db()
            for r_id, r_sname in c2.execute(
                "SELECT id, source_name FROM media_metadata WHERE id IN ({})".format(
                    ','.join(str(r[0]) for r in fs_need)),
            ):
                rid_to_sname[r_id] = r_sname
            c2.close()

        def _get_file_size(rid, sid, fid):
            try:
                req = urllib.request.urlopen(
                    f'https://api.telegram.org/bot{config.TOKEN}/getFile?file_id={fid}',
                    timeout=15
                )
                data = json.loads(req.read())
                return rid, sid, data['result']['file_size']
            except Exception:
                return rid, sid, None

        done = 0
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
            futures = [pool.submit(_get_file_size, rid, sid, fid) for rid, sid, fid in fs_need]
            for f in concurrent.futures.as_completed(futures):
                rid, sid, fs = f.result()
                if fs is not None:
                    rid_to_fs[rid] = fs
                    rid_to_sid[rid] = sid
                done += 1
                if done % 20 == 0:
                    print(f"  → getFile 进度 {done}/{len(fs_need)}")

    # ── 构建 file_size 匹配索引 ──
    fs_lookup = defaultdict(list)  # (source_id_int, file_size) → [(rid, source_name)]
    for rid, sid in rid_to_sid.items():
        try:
            sid_int = int(sid)
        except (ValueError, TypeError):
            continue
        fs_lookup[(sid_int, rid_to_fs[rid])].append((rid, rid_to_sname.get(rid, '')))

    # ── 补上 source_name（fuid_lookup 的记录已经有 source_name）──
    # 但 fs_lookup 的记录可能还有缺的，从 rows 补一下
    sname_map = {rid: sname for rid, sid, fid, fuid, sname in rows}

    # ── 单次扫描聊天记录 ──
    client = await _make_client()
    found = 0
    scanned = 0
    need_fs_match = bool(fs_lookup)
    need_fuid_match = bool(fuid_lookup)

    print(f"Phase 4: 扫描用户↔Bot 聊天记录（{total} 条待匹配，"
          f"file_unique_id:{len(fuid_lookup)}, file_size:{len(fs_lookup)}）...")

    log_every = max(200, (total - found) // 20)
    async for msg in client.get_chat_history(config.BOT_ID):
        chat = getattr(msg, 'forward_from_chat', None)
        if not chat:
            continue
        src_id = getattr(chat, 'id', None)
        if not src_id:
            continue

        orig_msg_id = getattr(msg, 'forward_from_message_id', None)
        orig_date = getattr(msg, 'forward_date', None)

        # ── 策略 1: 按 file_unique_id 匹配（视频/文档）──
        if need_fuid_match:
            for attr in ('photo', 'video', 'document', 'audio', 'animation'):
                media = getattr(msg, attr, None)
                if media:
                    fuid = getattr(media, 'file_unique_id', None)
                    if fuid in fuid_lookup:
                        rid, sname = fuid_lookup.pop(fuid)
                        update_record(rid,
                            message_id=orig_msg_id,
                            message_time=utc_to_local(orig_date).isoformat() if orig_date else None,
                        )
                        found += 1
                        if found <= 10:
                            print(f"  ✓[fuid] rid={rid} msg_id={orig_msg_id} sname={sname}")
                        if not fuid_lookup:
                            need_fuid_match = False
                        break

        # ── 策略 2: 按 (source_id, file_size) 匹配（照片）──
        if need_fs_match:
            media = msg.photo or msg.video or msg.document
            if media:
                fs = getattr(media, 'file_size', None) if not isinstance(media, list) else None
                if fs:
                    key = (src_id, fs)
                    if key in fs_lookup:
                        for rid, sname in fs_lookup.pop(key):
                            update_record(rid,
                                message_id=orig_msg_id,
                                message_time=utc_to_local(orig_date).isoformat() if orig_date else None,
                            )
                            found += 1
                            if found <= 10:
                                print(f"  ✓[fs] rid={rid} sid={src_id} fs={fs} msg_id={orig_msg_id}")
                        if not fs_lookup:
                            need_fs_match = False

        scanned += 1
        if scanned % log_every == 0:
            remain = len(fuid_lookup) + len(fs_lookup)
            print(f"  → 已扫 {scanned} 条消息，已匹配 {found}，剩余待匹配 {remain}")
        if not need_fuid_match and not need_fs_match:
            break

    await client.stop()
    print(f"Phase 4 完成: 扫描 {scanned} 条转发，匹配 {found}/{total} 条\n")
    remaining = (len(fuid_lookup) + len(fs_lookup))
    if remaining:
        print(f"  ⚠ 剩余 {remaining} 条未匹配（聊天记录可能已清除）")


# ═══════════════════════════════════════════════════════════════════════
# Phase 5: 回填 source_username + source_link2（纯 SQL，零网络）
#
# 从 source_link1 提取用户名，从 source_id+message_id 构造 source_link2
# ═══════════════════════════════════════════════════════════════════════

def backfill_phase5():
    """回填 source_username 和 source_link2。"""
    with _db_lock:
        conn = get_db()
        rows = conn.execute(
            "SELECT id, source_link1, source_id, message_id, source_username, source_link2 "
            "FROM media_metadata "
            "WHERE source_username IS NULL OR source_username = '' OR source_link2 IS NULL OR source_link2 = ''"
        ).fetchall()
        conn.close()

    updated_username = 0
    updated_link2 = 0
    for record_id, source_link1, source_id, msg_id, cur_username, cur_link2 in rows:
        kwargs = {}
        # 回填 source_username：从 source_link1 提取（格式: https://t.me/username/...）
        if not cur_username and source_link1:
            m = re.match(r'https://t\.me/([^/]+)/', source_link1)
            if m and m.group(1) != 'c':
                kwargs['source_username'] = m.group(1)
                updated_username += 1
        # 回填 source_link2：从 source_id + message_id 构造
        if not cur_link2 and source_id and msg_id is not None:
            if source_link1:
                kwargs['source_link2'] = f"https://t.me/c/{source_id}/{msg_id}"
            else:
                kwargs['source_link1'] = f"https://t.me/c/{source_id}/{msg_id}"
                kwargs['source_link2'] = ''
            updated_link2 += 1
        if kwargs:
            update_record(record_id, **kwargs)

    print(f"Phase 5: 回填 source_username: {updated_username} 条, source_link2: {updated_link2} 条\n")


# ═══════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════

async def main():
    from utils import init_db
    init_db()    # 确保数据库 schema 是最新的

    with _db_lock:
        total = get_db().execute("SELECT COUNT(*) FROM media_metadata").fetchone()[0]

    print(f"数据库总记录: {total}")
    backfill_phase3()        # 已有 message_id 的裸 link 补 /msg_id（扩大 Phase 1 覆盖）
    await backfill_phase1()  # 通过 source_link 的 msg_id 取 API 详情
    backfill_phase2()        # 从 source_link 截取 msg_id（纯 SQL，补漏）
    await backfill_phase4()  # 扫聊天记录，file_unique_id + file_size 双重匹配
    backfill_phase3()        # Phase 4 新填的 message_id 也写回 source_link
    backfill_phase5()        # 回填 source_username + source_link2
    print("全部完成")


if __name__ == '__main__':
    asyncio.run(main())
