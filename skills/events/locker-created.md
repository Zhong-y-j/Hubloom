---
event: locker.created
title: 钥匙柜已登记
description: 新钥匙柜已创建/登记，需核对列表是否可见并确认绑定小区是否正确。
payload_fields:
  - deviceId
hint_tags:
  - VehicleKeySmartLocker
  - GatedCommunity
---

# locker.created — 登记核对

## 目标

确认事件中的钥匙柜在业务系统中**可查到**，且**所属小区**与事件一致（或合理可解释）。

## 步骤

1. `list_api` 找到钥匙柜列表类接口（如 VehicleKeySmartLocker 分组下的 GetList）。
2. 用 `payload.deviceId`（及必要时柜名）过滤/查询钥匙柜列表。
3. 若事件带了小区名：再查小区列表（GatedCommunity GetList），核对小区是否存在。
4. 对比：柜名、设备号、所属小区是否与事件 payload 一致。
5. 交 Respond：**短表或条目**说明一致 / 不一致；不一致时写清差异与建议下一步。

## 禁止

- 禁止删除、禁用、改绑钥匙柜或小区。
- 禁止在未查到数据时宣称「登记成功」。
- 列表为空或 401：如实说明，不要编造柜/小区。

## 完成标准

用户（或事件回调消费方）能一眼看出：找没找到、绑没绑对、下一步要不要人介入。
