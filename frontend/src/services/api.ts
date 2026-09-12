import type { AxiosRequestConfig } from 'axios';

import axiosInstance from './axios';

export type ApiRequestConfig = Omit<AxiosRequestConfig, 'url' | 'method' | 'data' | 'params'>;

export const api = {
  // The response interceptor unwraps response.data. This is the sole REST
  // entry point used by application code; axios.ts is the private transport.
  get: <T = unknown>(
    url: string,
    params?: Record<string, unknown>,
    config?: ApiRequestConfig,
  ): Promise<T> => axiosInstance.get(url, { ...config, params }) as Promise<T>,

  post: <T = unknown>(
    url: string,
    data?: unknown,
    config?: ApiRequestConfig,
  ): Promise<T> => axiosInstance.post(url, data, config) as Promise<T>,

  put: <T = unknown>(
    url: string,
    data?: unknown,
    config?: ApiRequestConfig,
  ): Promise<T> => axiosInstance.put(url, data, config) as Promise<T>,

  delete: <T = unknown>(url: string, config?: ApiRequestConfig): Promise<T> =>
    axiosInstance.delete(url, config) as Promise<T>,

  patch: <T = unknown>(
    url: string,
    data?: unknown,
    config?: ApiRequestConfig,
  ): Promise<T> => axiosInstance.patch(url, data, config) as Promise<T>,
};
