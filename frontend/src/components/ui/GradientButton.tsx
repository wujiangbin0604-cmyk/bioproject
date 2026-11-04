import { Button } from '@arco-design/web-react';
import type { ButtonProps } from '@arco-design/web-react';
export function GradientButton({ className = '', ...props }: ButtonProps) { return <Button {...props} type="primary" className={`gradient-button ${className}`} />; }
