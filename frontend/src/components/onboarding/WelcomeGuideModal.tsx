import { Button, Modal } from '@arco-design/web-react';
import { Link } from 'react-router-dom';
import { Icon } from '../ui/Icon';

export function WelcomeGuideModal({ visible, onClose, afterClose }: { visible: boolean; onClose: () => void; afterClose?: () => void }) {
  return <Modal visible={visible} title={<span className="ufg-modal-title"><Icon name="dna" size={23} /> 欢迎引导 · 从这里开始</span>}
    onCancel={onClose} footer={<Button type="primary" onClick={onClose}>我知道了，开始探索</Button>}
    className="ufg-welcome-modal" style={{ width: 'min(580px, 94vw)' }} autoFocus focusLock afterClose={afterClose}>
    <div className="ufg-modal-body">
      <p className="ufg-modal-intro">欢迎来到 GeneScope 2.0！这份引导帮助首次访问的你，找到从互动学习到科研分析的起点。</p>
      <div className="ufg-modal-purpose"><Icon name="info" size={19} /><p><strong>为什么先看欢迎引导？</strong><span>先了解平台能做什么，再通过小游戏熟悉基因表达热图与关键特征，最后进入真实数据的分析流程。</span></p></div>
      <ol className="ufg-modal-steps">
        <li><span>1</span><div><h3>了解平台</h3><p>认识多数据集、模型实验和特征分析三个核心方向。</p></div></li>
        <li><span>2</span><div><h3>体验基因猎手</h3><p>从教学开始，观察热图、点击关键基因，再对照结算排名理解特征选择。</p></div></li>
        <li><span>3</span><div><h3>开始科研探索</h3><p>进入数据集中心，创建模型实验，通过实时监控、结果对比和特征分析理解结果。</p></div></li>
      </ol>
      <div className="ufg-modal-links"><Link to="/games/gene-hunter" onClick={onClose}><Icon name="game" size={17} /> 先玩基因猎手<Icon name="arrow" size={15} /></Link><Link to="/datasets" onClick={onClose}><Icon name="database" size={17} /> 探索数据集<Icon name="arrow" size={15} /></Link></div>
      <p className="ufg-modal-note">可随时通过课程答辩演示页的“了解欢迎引导设计”查看这份指南。小游戏使用合成数据，用于交互式学习。</p>
    </div>
  </Modal>;
}
