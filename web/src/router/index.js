import { createRouter, createWebHistory } from 'vue-router';

const routes = [
  {
    path: '/',
    name: 'feed',
    component: () => import('@/views/feed/index.vue'),
  },
  {
    path: '/tasks',
    name: 'tasks',
    component: () => import('@/views/tasks/index.vue'),
  },
  {
    path: '/storage',
    name: 'storage',
    component: () => import('@/views/storage/index.vue'),
  },
  {
    path: '/status',
    name: 'status',
    component: () => import('@/views/status/index.vue'),
  },
  {
    path: '/:pathMatch(.*)*',
    redirect: '/',
  },
];

export default createRouter({
  history: createWebHistory(),
  routes,
});
