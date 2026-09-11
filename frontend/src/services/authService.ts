import axiosInstance from './axios';

export const authService = {
  login: async (username: string, password: string) => {
    return axiosInstance.post('/auth/login/', { username, password });
  },

  register: async (data: {
    username: string;
    email: string;
    password: string;
    password_confirm: string;
  }) => {
    return axiosInstance.post('/auth/register/', data);
  },

  logout: async (refreshToken: string) => {
    return axiosInstance.post('/auth/logout/', { refresh: refreshToken });
  },

  getProfile: async () => {
    return axiosInstance.get('/auth/me/');
  },

  updateProfile: async (data: any) => {
    return axiosInstance.put('/auth/me/', data);
  },

  changePassword: async (data: {
    old_password: string;
    new_password: string;
    new_password_confirm: string;
  }) => {
    return axiosInstance.put('/auth/me/change-password/', data);
  },

  generateApiKey: async () => {
    return axiosInstance.post('/auth/me/generate-api-key/');
  },
};
