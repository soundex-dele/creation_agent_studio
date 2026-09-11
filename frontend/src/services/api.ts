import axiosInstance from './axios'

export const api = {
  // Generic HTTP methods (response.data is unwrapped by interceptor)
  get: <T = any>(url: string, params?: any): Promise<T> =>
    axiosInstance.get(url, { params }) as Promise<T>,

  post: <T = any>(url: string, data?: any): Promise<T> =>
    axiosInstance.post(url, data) as Promise<T>,

  put: <T = any>(url: string, data?: any): Promise<T> =>
    axiosInstance.put(url, data) as Promise<T>,

  delete: <T = any>(url: string): Promise<T> =>
    axiosInstance.delete(url) as Promise<T>,

  patch: <T = any>(url: string, data?: any): Promise<T> =>
    axiosInstance.patch(url, data) as Promise<T>,

  // Auth APIs
  login: (data: { username: string; password: string }) =>
    axiosInstance.post('/auth/login/', data),

  register: (data: { username: string; email: string; password: string; password_confirm: string }) =>
    axiosInstance.post('/auth/register/', data),

  logout: () =>
    axiosInstance.post('/auth/logout/'),

  // User APIs
  getUser: () =>
    axiosInstance.get('/auth/me/'),
}
