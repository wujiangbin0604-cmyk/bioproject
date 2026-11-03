from __future__ import annotations
from itertools import combinations
import platform
import time
from uuid import uuid4
import joblib
import numpy as np
import sklearn
from pydantic import BaseModel, ConfigDict, Field, model_validator
from typing import Literal
from sklearn.base import BaseEstimator, TransformerMixin, clone
from sklearn.feature_selection import f_classif
from sklearn.preprocessing import StandardScaler
from sklearn.svm import LinearSVC, SVC
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import RandomForestClassifier
from sklearn.pipeline import Pipeline
from sklearn.model_selection import StratifiedKFold, StratifiedGroupKFold
from sklearn.metrics import accuracy_score, balanced_accuracy_score, f1_score, confusion_matrix, classification_report
from threadpoolctl import threadpool_limits
from backend.app.lab_config import atomic_json
from .data import digest

ALGORITHMS = {'linear_svc':'LinearSVC', 'logistic_regression':'Logistic Regression', 'random_forest':'Random Forest', 'rbf_svm':'RBF SVM'}
METHODS = {'none':'全特征', 'anova':'ANOVA F-score', 'variance':'Variance Top-K', 'coefficient':'线性模型系数'}

class ExperimentConfig(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    dataset_id: Literal['pancan','gse4290','gse44076','gse45827']
    algorithms: list[Literal['linear_svc','logistic_regression','random_forest','rbf_svm']] = Field(default=['linear_svc'], min_length=1, max_length=4)
    selection: Literal['none','anova','variance','coefficient'] = 'anova'
    k: Literal[20,50,100,300,500,1000] = 50
    folds: int = Field(default=5, ge=2, le=10)
    seed: int = Field(default=42, ge=0, le=2147483647)
    repeats: int = Field(default=1, ge=1, le=5)
    c: float = Field(default=1., ge=.001, le=100)
    gamma: Literal['scale','auto'] = 'scale'
    n_estimators: int = Field(default=100, ge=10, le=300)
    max_depth: int | None = Field(default=10, ge=1, le=30)

    @model_validator(mode='after')
    def unique_algorithms(self):
        if len(set(self.algorithms)) != len(self.algorithms):
            raise ValueError('模型不能重复')
        if self.folds * self.repeats * len(self.algorithms) > 100:
            raise ValueError('单任务最多100次折拟合')
        return self

class FoldSelector(TransformerMixin, BaseEstimator):
    """Ranks only nonconstant features of the current training fold; never silently shrinks K."""
    def __init__(self, method='anova', k=50, seed=42):
        self.method, self.k, self.seed = method, k, seed

    def fit(self, X, y=None):
        self.n_features_in_ = X.shape[1]
        variance = np.var(X, axis=0)
        valid = np.isfinite(variance) & (variance > 0)
        if self.k > valid.sum():
            raise ValueError(f'K={self.k}超过当前训练折有效特征数{valid.sum()}')
        if self.method == 'anova':
            scores = np.full(X.shape[1], -np.inf)
            scores[valid] = f_classif(X[:,valid], y)[0]
            # Perfect within-class constant predictors may legitimately have infinite F statistics.
            scores = np.nan_to_num(scores, nan=-np.inf, posinf=np.finfo(float).max, neginf=-np.inf)
        elif self.method == 'variance':
            scores = variance.copy()
        else:
            base = Pipeline([('scale',StandardScaler()),('model',LinearSVC(C=.1, dual='auto', max_iter=50000, random_state=self.seed))])
            base.fit(X[:, valid], y)
            scores = np.full(X.shape[1], -np.inf)
            scores[valid] = np.mean(np.abs(base[-1].coef_), axis=0)
        scores[~valid] = -np.inf
        self.scores_ = scores
        self.mask_ = np.zeros(X.shape[1], dtype=bool)
        self.mask_[np.argsort(-scores, kind='stable')[:self.k]] = True
        self.n_samples_seen_ = len(X)
        return self

    def transform(self, X):
        return X[:, self.mask_]

    def get_support(self):
        return self.mask_

def pipeline(config, algorithm):
    classifiers = {
        'linear_svc':lambda:LinearSVC(C=config.c, dual='auto', max_iter=50000, random_state=config.seed),
        'logistic_regression':lambda:LogisticRegression(C=config.c, max_iter=5000, random_state=config.seed),
        'random_forest':lambda:RandomForestClassifier(n_estimators=config.n_estimators, max_depth=config.max_depth, n_jobs=1, random_state=config.seed),
        'rbf_svm':lambda:SVC(C=config.c, gamma=config.gamma, kernel='rbf', probability=False, cache_size=128, random_state=config.seed)}
    steps = [] if config.selection == 'none' else [('select',FoldSelector(config.selection,config.k,config.seed))]
    if algorithm != 'random_forest':
        steps.append(('scale', StandardScaler()))
    return Pipeline([*steps, ('model',classifiers[algorithm]())])

def splits(dataset, config):
    if min(np.unique(dataset.y, return_counts=True)[1]) < config.folds:
        raise ValueError('最小类别样本数小于交叉验证折数')
    indices=[]
    for repeat in range(config.repeats):
        if dataset.groups is None:
            splitter=StratifiedKFold(config.folds, shuffle=True, random_state=config.seed+repeat)
        else:
            if min(len(set(dataset.groups[dataset.y==c])) for c in np.unique(dataset.y)) < config.folds:
                raise ValueError('每类独立患者数不足以执行所选折数')
            splitter=StratifiedGroupKFold(config.folds, shuffle=True, random_state=config.seed+repeat)
        for fold, (train, valid) in enumerate(splitter.split(dataset.X, dataset.y, dataset.groups)):
            if dataset.groups is not None and set(dataset.groups[train]) & set(dataset.groups[valid]):
                raise ValueError('患者分组泄漏')
            if set(dataset.y[train]) != set(dataset.y) or set(dataset.y[valid]) != set(dataset.y):
                raise ValueError('当前分组划分缺少类别，请减少折数或更换随机种子')
            indices.append((repeat+1,fold+1,train,valid))
    return indices

def runtime():
    return {'python':platform.python_version(),'numpy':np.__version__,'scikit-learn':sklearn.__version__,'joblib':joblib.__version__}

def train(dataset, config, directory, publish, registry_root):
    indices=splits(dataset, config)
    atomic_json(directory/'split_indices.json', [{'repeat':r,'fold':f,'train':tr.tolist(),'validation':va.tolist()} for r,f,tr,va in indices])
    split_sha=digest(directory/'split_indices.json')
    folds, results, models=[],[],[]
    labels=sorted(set(dataset.y))
    for algorithm in config.algorithms:
        selections=[]
        per_truth, per_pred=[],[]
        for repeat, fold, train_idx, valid_idx in indices:
            publish(status='running',current_stage=f'{ALGORITHMS[algorithm]}：正在执行第{repeat}轮第{fold}/{config.folds}折')
            model=pipeline(config,algorithm)
            start=time.perf_counter()
            with threadpool_limits(limits=1):
                model.fit(dataset.X[train_idx],dataset.y[train_idx])
                predicted=model.predict(dataset.X[valid_idx])
            seconds=time.perf_counter()-start
            selector=model.named_steps.get('select')
            support=selector.get_support() if selector else np.ones(dataset.X.shape[1],dtype=bool)
            selections.append(set(np.flatnonzero(support).tolist()))
            # Saved fit audit binds preprocessing to each training fold.
            scaler=model.named_steps.get('scale')
            if scaler is not None and int(scaler.n_samples_seen_) != len(train_idx):
                raise ValueError('标准化器训练范围审计失败')
            row={'algorithm':algorithm,'repeat':repeat,'fold':fold,'macro_f1':float(f1_score(dataset.y[valid_idx],predicted,average='macro',zero_division=0)),
                 'accuracy':float(accuracy_score(dataset.y[valid_idx],predicted)), 'balanced_accuracy':float(balanced_accuracy_score(dataset.y[valid_idx],predicted)),
                 'fit_seconds':seconds,'n_features':int(support.sum()),'train_samples':len(train_idx),'validation_samples':len(valid_idx),
                 'scaler_samples_seen':int(scaler.n_samples_seen_) if scaler is not None else None,'group_overlap':0}
            folds.append(row)
            per_truth.extend(dataset.y[valid_idx]); per_pred.extend(predicted)
            atomic_json(directory/'folds.json', folds)
            publish(folds=folds,completed_folds=len(folds),progress=round(90*len(folds)/(len(indices)*len(config.algorithms)),2))
        counts=np.zeros(dataset.X.shape[1],dtype=int)
        for selected in selections:
            counts[list(selected)]+=1
        jaccard=[len(a&b)/len(a|b) for a,b in combinations(selections,2) if a|b]
        summary={m:{'mean':float(np.mean([v[m] for v in folds if v['algorithm']==algorithm])),
                    'std':float(np.std([v[m] for v in folds if v['algorithm']==algorithm],ddof=1))} for m in ['macro_f1','accuracy','balanced_accuracy']}
        result={'algorithm':algorithm,'metrics':summary,'fit_seconds':sum(v['fit_seconds'] for v in folds if v['algorithm']==algorithm),
                'n_features':len(selections[0]), 'labels':labels,'confusion_matrix':confusion_matrix(per_truth,per_pred,labels=labels).tolist(),
                'per_class':classification_report(per_truth,per_pred,output_dict=True,zero_division=0),
                'jaccard_mean':float(np.mean(jaccard)) if jaccard else None,
                'selection_frequency':[{'feature':dataset.feature_names[i],'count':int(counts[i]),'frequency':float(counts[i]/len(indices))} for i in np.argsort(-counts,kind='stable') if counts[i]>0],
                'statistics_scope':'折均值±样本标准差，仅描述性统计；重复CV的折相关，不作独立显著性检验'}
        publish(current_stage=f'{ALGORITHMS[algorithm]}：CV完成，拟合独立注册模型')
        fitted=pipeline(config,algorithm)
        with threadpool_limits(limits=1):
            fitted.fit(dataset.X,dataset.y)
        model_id=uuid4().hex
        folder=registry_root/model_id
        folder.mkdir(parents=True)
        artifact=folder/'pipeline.joblib'
        joblib.dump(fitted,artifact)
        selector=fitted.named_steps.get('select')
        score=selector.scores_ if selector is not None else np.var(dataset.X,axis=0)
        result['ranking']=[{'feature':dataset.feature_names[i],'score':float(score[i]) if np.isfinite(score[i]) else None} for i in np.argsort(-score,kind='stable')[:500]]
        metadata={'model_id':model_id,'dataset_id':config.dataset_id,'dataset_version':dataset.metadata['version'],
                  'task_definition':dataset.metadata['task_definition'],'feature_names':dataset.feature_names,
                  'feature_namespace':dataset.metadata['feature_namespace'], 'preprocessing_pipeline':str(fitted),
                  'split_protocol':dataset.split_protocol,'split_sha256':split_sha,'algorithm':algorithm,
                  'hyperparameters':config.model_dump(), 'training_timestamp':__import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat(),
                  'source_experiment_id':directory.name,'evaluation_metrics':summary,'runtime_versions':runtime(),
                  'artifact_sha256':digest(artifact),'model_version':model_id[:12], 'n_features':result['n_features'],
                  'input_preprocessing':'输入须使用与数据集导入后一致的表达尺度（见数据集预处理字段）',
                  'validation_scope':'内部交叉验证；注册模型随后拟合所有允许的开发样本，不包含PANCAN保留集'}
        atomic_json(folder/'metadata.json',metadata)
        result['model_id']=model_id
        results.append(result); models.append(model_id)
    output={'dataset_id':config.dataset_id,'dataset_version':dataset.metadata['version'],'task_definition':dataset.metadata['task_definition'],
            'split_protocol':dataset.split_protocol,'split_sha256':split_sha,'results':results,'model_ids':models,'configuration':config.model_dump()}
    atomic_json(directory/'results.json',output)
    return output
