import { ReactNode } from 'react';

interface AuthLayoutProps {
  children: ReactNode;
}

const AuthLayout: React.FC<AuthLayoutProps> = ({ children }) => {
  return (
    <div className="auth-layout relative flex h-screen w-full items-center justify-center overflow-hidden bg-void">
      {/* Animated background orbs (dark theme only) */}
      <div className="pointer-events-none absolute inset-0 overflow-hidden">
        <div className="animate-orb-float absolute -left-32 -top-32 h-96 w-96 rounded-full bg-primary/10 blur-3xl" />
        <div className="animate-orb-float absolute -bottom-32 -right-32 h-96 w-96 rounded-full bg-primary/5 blur-3xl" style={{ animationDelay: '-7s' }} />
        <div className="animate-orb-float absolute left-1/2 top-1/3 h-64 w-64 rounded-full bg-primary/8 blur-3xl" style={{ animationDelay: '-14s' }} />
      </div>
      {/* Content */}
      <div className="auth-layout-content relative z-10 w-full max-w-md">
        {children}
      </div>
    </div>
  );
};

export default AuthLayout;
