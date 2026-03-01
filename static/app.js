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
    await loadStats();
    await loadSources();
    await loadGroups();
    resetAndLoad();
    setupEventListeners();
}

function resetAndLoad() {
    offset = 0;
    isLastPage = false;
    mediaList = [];
    mediaContainer.innerHTML = '';
    loadMoreMedia();
}

// 加载统计信息
async function loadStats() {
    try {
        const response = await fetch('/api/stats');
        const data = await response.json();
        totalCountEl.textContent = `总量: ${data.total_count}`;
    } catch (err) {
        console.error('加载统计失败:', err);
        totalCountEl.textContent = '总量: --';
    }
}

// 加载来源分类
async function loadSources() {
    try {
        const response = await fetch('/api/sources');
        const sources = await response.json();
        // const firstTwo = sourceFilter.innerHTML; // 保持前两项（全部、单张） - 这一行在原始代码中不存在，且与后续逻辑冲突，移除
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
            mediaContainer.innerHTML = `<div class="error">加载失败: ${err.message}</div>`;
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
        
        // 查找或创建 Group Section
        let sectionId = `group-${gid}`;
        let section = document.getElementById(sectionId);
        
        if (!section) {
            section = document.createElement('section');
            section.id = sectionId;
            section.className = 'group-section';
            
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
            
            let actionsHtml = gid !== 'single' 
                ? `<div class="group-actions"><button class="danger-btn btn-delete-group" onclick="deleteGroup('${gid}')">🗑️ 删除整组</button></div>` 
                : '';
            
            header.innerHTML = `<h2 title="${fullCaption}">${groupTitle}</h2>${actionsHtml}`;
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
    if (!confirm(`确定要彻底删除整个媒体组 ${groupId} 吗？\n此操作将删除该组下的所有文件及记录，不可恢复。`)) return;

    try {
        const response = await fetch(`/api/media_group/${groupId}`, { method: 'DELETE' });
        if (response.ok) {
            resetAndLoad();
            loadStats();
        } else {
            const error = await response.json();
            alert('删除失败: ' + (error.detail || '未知原因'));
        }
    } catch (err) {
        alert('系统错误: ' + err.message);
    }
}

// 创建媒体卡片
function createMediaCard(item) {
    const card = document.createElement('div');
    card.className = 'media-card';
    
    const isVideo = item.media_type === 'video';
    let relativePath = '';
    if (!item.source) {
        relativePath = `unsorted/${item.filename}`;
    } else if (['user', 'private_user', 'unknown_forward'].includes(item.source_type)) {
        relativePath = `direct_messages/${item.source}/${item.filename}`;
    } else {
        relativePath = `${item.source}/${item.filename}`;
    }
    const mediaUrl = `/media/${relativePath}`;

    let previewHtml = isVideo 
        ? `<video class="media-preview" muted preload="metadata"><source src="${mediaUrl}" type="video/mp4"></video>` 
        : `<img class="media-preview" src="${mediaUrl}" loading="lazy">`;

    card.innerHTML = `
        ${previewHtml}
        <div class="type-badge">${isVideo ? '🎥 视频' : '🖼️ 图片'}</div>
        <div class="card-overlay">
            <div class="card-caption">${item.caption || '无标题'}</div>
            <div class="card-meta">${item.datetime.split('T')[0]}</div>
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
    const sourceLinkHtml = item.source_link 
        ? `<a href="${item.source_link}" target="_blank" style="color: var(--accent-color); font-weight: bold; margin-left:10px;">(去原消息 🔗)</a>` 
        : '';
    
    modalMeta.innerHTML = `
        <div class="meta-item"><strong>文件名:</strong> ${item.filename}</div>
        <div class="meta-item"><strong>来源:</strong> ${sourceText}${sourceLinkHtml}</div>
        <div class="meta-item"><strong>时间:</strong> ${item.datetime.replace('T', ' ').split('.')[0]}</div>
    `;
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
        if (!confirm('确定要删除这个资源吗？此操作将同时删除本地文件和数据库记录。')) return;
        try {
            const response = await fetch(`/api/media/${currentMediaId}`, { method: 'DELETE' });
            if (response.ok) {
                modal.style.display = 'none';
                stopMedia();
                resetAndLoad();
                loadStats();
            } else {
                alert('删除失败');
            }
        } catch (err) {
            alert('系统错误: ' + err.message);
        }
    };
}

init();
