declare module 'virtual:application-packages' {
  const applications: import('./platform/applications').ApplicationFrontendModule[];
  export default applications;
}
