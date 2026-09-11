import axios from 'axios';
import { message } from 'antd';
import { useAuthStore } from '@/stores/useAuthStore';
import { API_BASE_URL } from './apiBaseUrl';

const axiosInstance = axios.create({
  baseURL: API_BASE_URL,
  timeout: 10000,
  headers: {
    'Content-Type': 'application/json',
  },
});

// Request interceptor
axiosInstance.interceptors.request.use(
  (config) => {
    const token = useAuthStore.getState().token;
    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }
    let organizationId: string | null = null;
    try {
      const persisted = JSON.parse(localStorage.getItem('organization-storage') || '{}');
      organizationId = persisted?.state?.currentOrganizationId || null;
    } catch {
      organizationId = null;
    }
    if (organizationId) {
      config.headers['X-Organization-ID'] = organizationId;
    }
    return config;
  },
  (error) => {
    return Promise.reject(error);
  }
);

// Response interceptor
let isRefreshing = false;
let failedQueue: Array<{
  resolve: (value?: any) => void;
  reject: (reason?: any) => void;
}> = [];

const processQueue = (error: any, token: string | null = null) => {
  failedQueue.forEach((prom) => {
    if (error) {
      prom.reject(error);
    } else {
      prom.resolve(token);
    }
  });
  failedQueue = [];
};

// Force re-login: synchronously clear local auth state, then redirect to the
// login page. Guarded so a burst of simultaneous 401s only redirects once.
let redirectingToLogin = false;
const redirectToLogin = () => {
  if (redirectingToLogin) return;
  redirectingToLogin = true;
  useAuthStore.getState().clearAuth();
  window.location.href = '/auth/login';
};

// Endpoints that own their own 401s (wrong password, invalid refresh token):
// we must NOT auto-refresh or redirect for these — surface the error to the
// caller. Without this, a failed /token/refresh/ 401 re-enters this interceptor
// while isRefreshing is already true, gets parked on failedQueue, and deadlocks
// — so the re-login redirect would never fire.
const AUTH_PATHS = [
  '/auth/login/',
  '/auth/register/',
  '/auth/token/refresh/',
  '/auth/logout/',
];

axiosInstance.interceptors.response.use(
  (response) => {
    return response.data;
  },
  async (error) => {
    const originalRequest = error.config;
    const status = error.response?.status;
    const isAuthRequest = AUTH_PATHS.some((p) => originalRequest.url?.includes(p));

    // 401 on an auth endpoint (login/register/refresh/logout): hand it back to
    // the caller (e.g. the login form showing "wrong password").
    if (status === 401 && isAuthRequest) {
      return Promise.reject(error);
    }

    // 401 on a protected endpoint, first attempt: refresh once, then retry.
    if (status === 401 && !originalRequest._retry) {
      if (isRefreshing) {
        return new Promise((resolve, reject) => {
          failedQueue.push({ resolve, reject });
        })
          .then((token) => {
            originalRequest.headers.Authorization = `Bearer ${token}`;
            return axiosInstance(originalRequest);
          })
          .catch((err) => Promise.reject(err));
      }

      originalRequest._retry = true;
      isRefreshing = true;

      try {
        await useAuthStore.getState().refreshAccessToken();
        const newToken = useAuthStore.getState().token;
        processQueue(null, newToken);
        originalRequest.headers.Authorization = `Bearer ${newToken}`;
        return axiosInstance(originalRequest);
      } catch (refreshError) {
        processQueue(refreshError, null);
        redirectToLogin();
        return Promise.reject(refreshError);
      } finally {
        isRefreshing = false;
      }
    }

    // Everything else. A 401 reaching here means refresh was skipped (auth
    // endpoint) or retry already exhausted — force re-login.
    if (error.response) {
      switch (status) {
        case 401:
          redirectToLogin();
          break;
        case 403:
          message.error('拒绝访问');
          break;
        case 404:
          message.error('请求错误，未找到该资源');
          break;
        case 500:
          message.error('服务器错误');
          break;
        default:
          message.error(error.response.data?.detail || '请求失败');
      }
    }

    return Promise.reject(error);
  }
);

export default axiosInstance;
