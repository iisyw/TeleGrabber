// 已登录凭据 (Basic Auth)，仅保存在内存中，刷新页面后需重新输入
let authHeader = null;

// HTML 转义，防止 caption/filename 等用户可控字段造成 XSS
function escapeHtml(value) {
    if (value === null || value === undefined) return '';
    return String(value)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

// 构造带鉴权头的请求选项
function authFetch(url, options = {}) {
    const opts = { ...options };
    if (authHeader) {
        opts.headers = { ...(opts.headers || {}), 'Authorization': authHeader };
    }
    return fetch(url, opts);
}

// 轻量提示 toast
function showToast(message, type = 'success', duration = 2500) {
    const container = document.getElementById('toastContainer');
    if (!container) return;
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.textContent = message;
    container.appendChild(toast);
    setTimeout(() => {
        toast.classList.add('fade-out');
        toast.addEventListener('animationend', () => toast.remove());
    }, duration);
}

// 自定义确认对话框，返回 Promise<boolean>
function confirmDialog(message, { title = '确认操作', okText = '确认删除' } = {}) {
    return new Promise(resolve => {
        const overlay = document.getElementById('confirmDialog');
        const okBtn = document.getElementById('confirmOk');
        const cancelBtn = document.getElementById('confirmCancel');
        document.getElementById('confirmTitle').textContent = title;
        document.getElementById('confirmMessage').textContent = message;
        okBtn.textContent = okText;

        const cleanup = (result) => {
            overlay.classList.remove('show');
            okBtn.onclick = null;
            cancelBtn.onclick = null;
            document.removeEventListener('keydown', onKey);
            overlay.removeEventListener('click', onBackdrop);
            resolve(result);
        };
        const onKey = (e) => {
            if (e.key === 'Escape') cleanup(false);
            else if (e.key === 'Enter') cleanup(true);
        };
        const onBackdrop = (e) => { if (e.target === overlay) cleanup(false); };

        okBtn.onclick = () => cleanup(true);
        cancelBtn.onclick = () => cleanup(false);
        document.addEventListener('keydown', onKey);
        overlay.addEventListener('click', onBackdrop);
        overlay.classList.add('show');
    });
}

// 弹出登录框并执行写操作；遇到 401 时提示重新输入
async function authedWrite(url, options) {
    let response = await authFetch(url, options);
    if (response.status === 401) {
        const username = prompt('请输入管理后台用户名:');
        if (username === null) return null;
        const password = prompt('请输入密码:');
        if (password === null) return null;
        authHeader = 'Basic ' + btoa(`${username}:${password}`);
        response = await authFetch(url, options);
        if (response.status === 401) {
            authHeader = null;
            showToast('用户名或密码错误', 'error');
            return null;
        }
    }
    return response;
}

let currentSearch = '';
let currentSource = '';
let currentGroup = '';
let currentMediaId = null;

// 分页与加载状态
let offset = 0;
const limit = 30;
let isLoading = false;
let isLastPage = false;
let mediaList = []; // 存储所有已加载的媒体

// DOM 元素
const mediaContainer = document.getElementById('mediaContainer');
const totalCountEl = document.getElementById('totalCount');
const sourceFilter = document.getElementById('sourceFilter');
const groupFilter = document.getElementById('groupFilter');
const searchInput = document.getElementById('searchInput');
const searchBtn = document.getElementById('searchBtn');
const modal = document.getElementById('modal');
const closeModal = document.querySelector('.close-modal');
const modalMedia = document.getElementById('modalMedia');
const modalCaption = document.getElementById('modalCaption');
const modalMeta = document.getElementById('modalMeta');
const modalDeleteBtn = document.getElementById('modalDeleteBtn');

// 新增 DOM: 底部加载触发器和回到顶部按钮
const loadingTrigger = document.createElement('div');
loadingTrigger.className = 'loading-trigger';
loadingTrigger.innerHTML = '<div class="loader" style="width:24px; height:24px; border-width:3px;"></div><span style="margin-left:12px;">正在加载更多资源...</span>';

const backToTopBtn = document.createElement('button');
backToTopBtn.className = 'back-to-top';
backToTopBtn.innerHTML = '▲';
document.body.appendChild(backToTopBtn);

// 初始化
async function init() {
    await loadSources();
    await loadGroups();
    resetAndLoad();   // 内部已调用 loadStats
    setupEventListeners();
}

function resetAndLoad() {
    offset = 0;
    isLastPage = false;
    mediaList = [];
    mediaContainer.innerHTML = '';
    loadStats();       // 同步刷新当前筛选条件下的数量
    loadMoreMedia();
}

// 加载统计信息（跟随当前搜索/筛选条件）
async function loadStats() {
    let url = '/api/stats';
    const qs = [];
    if (currentSearch) qs.push(`search=${encodeURIComponent(currentSearch)}`);
    if (currentSource) qs.push(`source=${encodeURIComponent(currentSource)}`);
    if (currentGroup) qs.push(`media_group_id=${encodeURIComponent(currentGroup)}`);
    if (qs.length) url += '?' + qs.join('&');

    try {
        const response = await fetch(url);
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const data = await response.json();
        totalCountEl.textContent = data.filtered
            ? `找到: ${data.total_count}`
            : `总量: ${data.total_count}`;
    } catch (err) {
        console.error('加载统计失败:', err);
        totalCountEl.textContent = '总量: --';
    }
}

// 加载来源分类
async function loadSources() {
    try {
        const response = await fetch('/api/sources');
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const sources = await response.json();
        sourceFilter.innerHTML = '<option value="">所有来源渠道</option>';
        sources.forEach(source => {
            const option = document.createElement('option');
            option.value = source;
            option.textContent = source;
            sourceFilter.appendChild(option);
        });
    } catch (err) {
        console.error('加载来源失败:', err);
    }
}

// 加载媒体组列表
async function loadGroups() {
    groupFilter.innerHTML = '<option value="">全部展示</option><option value="single">仅单张内容</option>';
    let url = '/api/media_groups';
    if (currentSource) url += `?source=${encodeURIComponent(currentSource)}`;

    try {
        const response = await fetch(url);
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const groups = await response.json();
        groups.forEach(groupId => {
            const option = document.createElement('option');
            option.value = groupId;
            option.textContent = `媒体组: ${groupId}`;
            groupFilter.appendChild(option);
        });
    } catch (err) {
        console.error('加载媒体组失败:', err);
    }
}

// 分页加载媒体
async function loadMoreMedia() {
    if (isLoading || isLastPage) return;
    
    isLoading = true;
    mediaContainer.appendChild(loadingTrigger);
    
    let url = `/api/media?limit=${limit}&offset=${offset}`;
    if (currentSearch) url += `&search=${encodeURIComponent(currentSearch)}`;
    if (currentSource) url += `&source=${encodeURIComponent(currentSource)}`;
    if (currentGroup) url += `&media_group_id=${encodeURIComponent(currentGroup)}`;

    try {
        const response = await fetch(url);
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const newData = await response.json();
        
        if (newData.length < limit) {
            isLastPage = true;
        }
        
        offset += newData.length;
        mediaList = mediaList.concat(newData);
        renderGroupedGallery(newData, offset === newData.length); // 第二个参数标识是否是首页
    } catch (err) {
        console.error('加载失败:', err);
        if (offset === 0) {
            mediaContainer.innerHTML = `<div class="error">加载失败: ${escapeHtml(err.message)}</div>`;
        }
    } finally {
        isLoading = false;
        if (loadingTrigger.parentNode) {
            mediaContainer.removeChild(loadingTrigger);
        }
        
        if (isLastPage && mediaList.length > 0) {
            const endNote = document.createElement('div');
            endNote.className = 'loading-trigger';
            endNote.textContent = '--- 已加载全部内容 ---';
            mediaContainer.appendChild(endNote);
        }
    }
}

// 核心渲染逻辑：支持平滑追加与媒体组缝合
function renderGroupedGallery(newData, isFirstPage) {
    if (isFirstPage && newData.length === 0) {
        mediaContainer.innerHTML = '<div class="no-data">暂无下载记录</div>';
        return;
    }

    newData.forEach(item => {
        const gid = item.media_group_id && item.media_group_id !== 'single' ? item.media_group_id : 'single';

        // 查找或创建 Group Section（用 dataset 而非 id 选择器，避免 gid 含特殊字符）
        let section = mediaContainer.querySelector(`section.group-section[data-gid="${CSS.escape(gid)}"]`);

        if (!section) {
            section = document.createElement('section');
            section.className = 'group-section';
            section.dataset.gid = gid;
            
            // 组标题处理
            let groupTitle = gid === 'single' ? '单张内容 / 其他' : `媒体组: ${gid}`;
            let fullCaption = '';
            
            // 查找描述
            if (gid !== 'single') {
                const representative = mediaList.find(m => m.media_group_id === gid && m.caption);
                if (representative) {
                    fullCaption = representative.caption;
                    const short = fullCaption.length > 30 ? fullCaption.substring(0, 30) + '...' : fullCaption;
                    groupTitle = `媒体组: ${gid} (${short})`;
                }
            }

            const header = document.createElement('div');
            header.className = 'group-header';

            const h2 = document.createElement('h2');
            h2.title = fullCaption;
            h2.textContent = groupTitle;
            header.appendChild(h2);

            if (gid !== 'single') {
                const actions = document.createElement('div');
                actions.className = 'group-actions';
                const delBtn = document.createElement('button');
                delBtn.className = 'danger-btn btn-delete-group';
                delBtn.textContent = '🗑️ 删除整组';
                delBtn.onclick = () => deleteGroup(gid);
                actions.appendChild(delBtn);
                header.appendChild(actions);
            }
            section.appendChild(header);
            
            const grid = document.createElement('div');
            grid.className = 'group-grid';
            section.appendChild(grid);
            
            mediaContainer.appendChild(section);
        }

        // 将卡片加入对应的网格
        const grid = section.querySelector('.group-grid');
        const card = createMediaCard(item);
        grid.appendChild(card);
    });
}

// 删除整个媒体组
async function deleteGroup(groupId) {
    const ok = await confirmDialog(
        `确定要彻底删除整个媒体组吗？\n此操作将删除该组下的所有文件及记录，不可恢复。`,
        { title: '删除媒体组', okText: '删除整组' }
    );
    if (!ok) return;

    try {
        const response = await authedWrite(`/api/media_group/${groupId}`, { method: 'DELETE' });
        if (!response) return;
        if (response.ok) {
            // 局部移除整个分组，不刷新页面、不重置滚动
            const section = mediaContainer.querySelector(`section.group-section[data-gid="${CSS.escape(groupId)}"]`);
            if (section) section.remove();
            mediaList = mediaList.filter(m => m.media_group_id !== groupId);
            loadStats();
            showToast('媒体组已删除', 'success');
        } else {
            const error = await response.json().catch(() => ({}));
            showToast('删除失败: ' + (error.detail || '未知原因'), 'error');
        }
    } catch (err) {
        showToast('系统错误: ' + err.message, 'error');
    }
}

// 创建媒体卡片
function createMediaCard(item) {
    const card = document.createElement('div');
    card.className = 'media-card';
    card.dataset.id = item.id;
    
    const isVideo = item.media_type === 'video';
    let relativePath = '';
    if (!item.source) {
        relativePath = `unsorted/${item.filename}`;
    } else if (['user', 'private_user', 'unknown_forward'].includes(item.source_type)) {
        relativePath = `direct_messages/${item.source}/${item.filename}`;
    } else {
        relativePath = `${item.source}/${item.filename}`;
    }
    // 对每一段路径做 URI 编码，避免特殊字符破坏 URL
    const mediaUrl = '/media/' + relativePath.split('/').map(encodeURIComponent).join('/');

    const previewHtml = isVideo
        ? `<video class="media-preview" muted preload="metadata"><source src="${mediaUrl}" type="video/mp4"></video>`
        : `<img class="media-preview" src="${mediaUrl}" loading="lazy">`;

    const dateText = item.datetime ? item.datetime.split('T')[0] : '';
    card.innerHTML = `
        ${previewHtml}
        <div class="type-badge">${isVideo ? '🎥 视频' : '🖼️ 图片'}</div>
        <div class="card-overlay">
            <div class="card-caption">${escapeHtml(item.caption || '无标题')}</div>
            <div class="card-meta">${escapeHtml(dateText)}</div>
        </div>
    `;

    card.onclick = () => openModal(item, mediaUrl);
    return card;
}

// 模态框逻辑
function openModal(item, url) {
    currentMediaId = item.id;
    if (item.media_type === 'video') {
        modalMedia.innerHTML = `<video id="activeVideo" controls autoplay style="width:100%; height:100%;"><source src="${url}" type="video/mp4"></video>`;
    } else {
        modalMedia.innerHTML = `<img src="${url}" style="max-width:100%; max-height:100%;">`;
    }
    
    modalCaption.textContent = item.caption || '无标题';

    const sourceText = item.source || '未知';
    const datetimeText = item.datetime ? item.datetime.replace('T', ' ').split('.')[0] : '';

    // 用 DOM API 构造，避免 filename/source/source_link 引发 XSS
    modalMeta.innerHTML = '';

    const fileRow = document.createElement('div');
    fileRow.className = 'meta-item';
    fileRow.innerHTML = '<strong>文件名:</strong> ';
    fileRow.appendChild(document.createTextNode(item.filename || ''));

    const sourceRow = document.createElement('div');
    sourceRow.className = 'meta-item';
    sourceRow.innerHTML = '<strong>来源:</strong> ';
    sourceRow.appendChild(document.createTextNode(sourceText));
    if (item.source_link) {
        const link = document.createElement('a');
        link.href = item.source_link;
        link.target = '_blank';
        link.rel = 'noopener noreferrer';
        link.style.cssText = 'color: var(--accent-color); font-weight: bold; margin-left:10px;';
        link.textContent = '(去原消息 🔗)';
        sourceRow.appendChild(link);
    }

    const timeRow = document.createElement('div');
    timeRow.className = 'meta-item';
    timeRow.innerHTML = '<strong>时间:</strong> ';
    timeRow.appendChild(document.createTextNode(datetimeText));

    modalMeta.append(fileRow, sourceRow, timeRow);
    modal.style.display = 'block';
}

function stopMedia() {
    const video = document.getElementById('activeVideo');
    if (video) {
        video.pause();
        video.src = "";
        video.load();
    }
    modalMedia.innerHTML = '';
}

function setupEventListeners() {
    // 使用 IntersectionObserver 替代传统的 scroll 监听，性能更佳且无抖动
    const observer = new IntersectionObserver((entries) => {
        if (entries[0].isIntersecting && !isLoading && !isLastPage) {
            loadMoreMedia();
        }
    }, { threshold: 0.1, rootMargin: '200px' });

    // 观察一个虚拟的占位点，或者直接观察 mediaContainer 的末尾
    // 我们可以动态创建一个观察哨
    const sentinel = document.createElement('div');
    sentinel.id = 'pagination-sentinel';
    sentinel.style.height = '1px';
    mediaContainer.after(sentinel);
    observer.observe(sentinel);

    // 回到顶部按钮显示控制（仍需监听 scroll 以便实时更新置顶按钮）
    window.addEventListener('scroll', () => {
        if (window.scrollY > 500) {
            backToTopBtn.style.display = 'flex';
        } else {
            backToTopBtn.style.display = 'none';
        }
    }, { passive: true });

    backToTopBtn.onclick = () => {
        window.scrollTo({ top: 0, behavior: 'smooth' });
    };

    closeModal.onclick = () => {
        modal.style.display = 'none';
        stopMedia();
    };
    
    sourceFilter.onchange = (e) => { 
        currentSource = e.target.value; 
        currentGroup = '';
        loadGroups();
        resetAndLoad();
    };

    groupFilter.onchange = (e) => {
        currentGroup = e.target.value;
        resetAndLoad();
    };
    
    searchBtn.onclick = () => { currentSearch = searchInput.value; resetAndLoad(); };
    searchInput.onkeypress = (e) => { if (e.key === 'Enter') { currentSearch = searchInput.value; resetAndLoad(); } };

    modalDeleteBtn.onclick = async () => {
        const ok = await confirmDialog(
            '确定要删除这个资源吗？此操作将同时删除本地文件和数据库记录。',
            { title: '删除资源', okText: '彻底删除' }
        );
        if (!ok) return;
        const targetId = currentMediaId;
        try {
            const response = await authedWrite(`/api/media/${targetId}`, { method: 'DELETE' });
            if (!response) return;
            if (response.ok) {
                modal.style.display = 'none';
                stopMedia();
                removeCardFromDom(targetId);
                loadStats();
                showToast('已删除', 'success');
            } else {
                const error = await response.json().catch(() => ({}));
                showToast('删除失败: ' + (error.detail || '未知原因'), 'error');
            }
        } catch (err) {
            showToast('系统错误: ' + err.message, 'error');
        }
    };
}

// 从 DOM 中局部移除一张卡片；若所在分组随之变空，则连同分组一起移除
function removeCardFromDom(id) {
    const card = mediaContainer.querySelector(`.media-card[data-id="${CSS.escape(String(id))}"]`);
    if (!card) return;
    const section = card.closest('.group-section');
    card.remove();
    mediaList = mediaList.filter(m => String(m.id) !== String(id));
    if (section && section.querySelectorAll('.media-card').length === 0) {
        section.remove();
    }
}

init();
