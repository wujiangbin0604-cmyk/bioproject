import type { PropsWithChildren } from 'react';
import { variants } from '../../animations/variants';
export function PageTransition({ children }: PropsWithChildren) { return <div className={variants.page}>{children}</div>; }
