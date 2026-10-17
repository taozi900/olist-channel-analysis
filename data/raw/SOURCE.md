# 数据来源与许可

- 数据集：Marketing Funnel by Olist
- 发布者：Olist（Kaggle账号olistbr）
- 官方页面：https://www.kaggle.com/datasets/olistbr/marketing-funnel-olist
- 官方背景：https://github.com/olist/work-at-olist-marketing
- 下载接口：https://www.kaggle.com/api/v1/datasets/download/olistbr/marketing-funnel-olist
- 元数据接口：https://www.kaggle.com/api/v1/datasets/view/olistbr/marketing-funnel-olist
- 此包版本：Kaggle数据集第2版，元数据更新时间2018-11-16。
- 下载时间：详见source_manifest.json的downloaded_at_utc。
- 发布方许可：Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International（CC BY-NC-SA 4.0）。
- 许可文本：https://creativecommons.org/licenses/by-nc-sa/4.0/legalcode

Olist将其描述为真实、匿名化、随机抽样的商家营销线索数据。本文依据发布说明注明来源，不代表对原始业务采集过程进行了独立审计。

此包保留原始ZIP和解压后的两张CSV，CSV没有改字节、删除记录、填补缺失或修正日期。source_metadata.json是下载时的发布页API元数据快照；source_manifest.json记录版本、文件大小和SHA256。ZIP已通过CRC检查；发布方未提供独立校验和，故本地哈希只能用于一致性检查。

数据采样对象是请求联系的商家线索，不是消费者订单。发布方说明线索请求联系的采样期间为2017年6月至2018年6月；实际文件内出现的日期范围由01脚本另行检查，不把采样期间当作所有线索的完整随访区间。

发布方提醒同一商家可能从多个来源注册。原始文件每个mql_id只有一条来源标签，不能据此构造多触点路径或把所有线索当作独立商家。

数据及原始资料继续受其原始许可约束；本项目的学习脚本、文档不能改变数据许可。转载、修改和分享时请保留Olist署名、来源、许可链接及变更说明，并遵守非商业和相同方式共享等条件。作者与Olist无隶属关系。
