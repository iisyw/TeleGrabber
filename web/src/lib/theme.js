import { ref } from 'vue';

const STORAGE_KEY = 'telegrabber-theme';

function initialTheme() {
  const fromDom = document.documentElement.dataset.theme;
  if (fromDom === 'light' || fromDom === 'dark') return fromDom;
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored === 'light' || stored === 'dark') return stored;
  } catch {
    // localStorage 不可用时忽略
  }
  return 'dark';
}

export const theme = ref(initialTheme());

export function applyTheme(next) {
  const value = next === 'light' ? 'light' : 'dark';
  theme.value = value;
  document.documentElement.dataset.theme = value;
  document.documentElement.classList.toggle('dark', value === 'dark');
  document.documentElement.style.colorScheme = value;
  try {
    localStorage.setItem(STORAGE_KEY, value);
  } catch {
    // localStorage 不可用时忽略
  }
  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta) {
    meta.setAttribute('content', value === 'dark' ? '#17212b' : '#ffffff');
  }
}

export function toggleTheme() {
  applyTheme(theme.value === 'dark' ? 'light' : 'dark');
}

export function initTheme() {
  applyTheme(theme.value);
}
