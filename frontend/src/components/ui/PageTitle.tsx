import type { ReactNode } from 'react';
import { Icon } from './Icon';
import type { IconName } from './Icon';
export function PageTitle({ title, description, icon, extra }: { title: string; description: string; icon: IconName; extra?: ReactNode }) {
  return <header className="ui-page-title"><div className="title-icon"><Icon name={icon} size={25} /></div><div><h1>{title}</h1><p>{description}</p></div>{extra && <div className="ui-title-extra">{extra}</div>}</header>;
}
