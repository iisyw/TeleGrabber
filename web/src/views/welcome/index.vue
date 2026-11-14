<template>
  <main class="welcome-page">
    <section class="welcome-card">
      <div class="welcome-brand">
        <span class="welcome-logo" aria-hidden="true">
          <svg viewBox="0 0 24 24" width="28" height="28">
            <path
              fill="currentColor"
              d="M9.78 18.65l.28-4.23 7.68-6.92c.34-.31-.07-.46-.52-.19L7.74 13.3 3.64 12c-.88-.25-.89-.86.2-1.3l15.43-5.95c.74-.28 1.38.18 1.11 1.3l-2.62 12.34c-.19.9-.74 1.12-1.5.7l-4.13-3.05-1.99 1.93c-.23.23-.42.43-.83.43z"
            />
          </svg>
        </span>
        <div>
          <h1>TeleGrabber</h1>
          <p>Telegram 媒体归档工具</p>
        </div>
      </div>

      <p class="welcome-desc">
        这里汇总你归档的图片、视频与文件。先停在欢迎页，进入后再加载消息流，
        避免打开页面时被大量媒体突然刷屏。
      </p>

      <div class="welcome-features">
        <div class="welcome-feature">
          <span class="welcome-feature-title">消息流</span>
          <span class="welcome-feature-desc">按来源浏览、搜索和预览已归档媒体</span>
        </div>
        <div class="welcome-feature">
          <span class="welcome-feature-title">存储管理</span>
          <span class="welcome-feature-desc">查看各来源占用、重复媒体与磁盘空间</span>
        </div>
        <div class="welcome-feature">
          <span class="welcome-feature-title">系统状态</span>
          <span class="welcome-feature-desc">检查 Bot、User API、健康状态与运行配置</span>
        </div>
      </div>

      <div class="welcome-actions">
        <router-link to="/feed" class="welcome-enter">进入消息流</router-link>
        <router-link to="/storage" class="welcome-link">存储管理</router-link>
        <router-link to="/status" class="welcome-link">系统状态</router-link>
      </div>

      <p class="welcome-hint">左侧栏可随时切换页面；媒体列表只会在进入消息流后加载。</p>
    </section>
  </main>
</template>

<style scoped lang="scss" src="./index.scss"></style>
