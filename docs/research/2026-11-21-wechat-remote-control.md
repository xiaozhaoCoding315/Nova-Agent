# 微信远程控制 Nova Agent：官方能力与安全架构调研

日期：2026-11-21

范围：本文只做官方能力核实与架构调研，不修改产品代码、不配置公众号、不部署、不提交。重点回答：用户在手机微信扫码后查看本地优先 Agent 的进度、发送有限指令、接收完成或待审批通知，哪些微信通道可用，如何在不暴露本地端口的前提下安全实现。

标记说明：

- 【事实】官方文档、官方帮助页或标准原文直接支持，并在就近位置附 URL。
- 【推断】由已核实事实导出的工程判断，不等同于平台承诺。
- 【建议】面向 Nova 的设计建议，非平台事实。
- 【未核实】未找到官方依据、官方文档互相冲突，或必须看具体账号后台/目标设备才能确定。

优先来源为微信公众平台、企业微信、微信开放平台官方文档，以及必要的 Web/密码学标准。官方文档会更新，具体账号的真实权限应以账号后台和正式接口返回为准。

---

## 0. 结论摘要

【建议】Nova 的主路径应当是“手机工作台”，不是公众号：

1. 本地 Agent 只主动出站，通过 mTLS + WSS 连接用户自有的受控中继；本地不监听公网端口。
2. 桌面端生成一次性、短时、单次使用的绑定二维码或链接；手机扫码进入手机工作台，生成设备密钥，经本地确认后完成绑定。
3. 工作台只显示脱敏进度，审批、继续、停止等操作都封装为有限意图；所有远程指令需设备签名、限时、可撤销、可审计。
4. 危险操作仍由本地权限引擎审批，远程只能处理本地明确暴露的低/中风险审批，不能绕开本地策略。
5. 微信只作为可选入口：手机微信扫一扫打开 HTTPS 页面，或作为可选通知适配层；公众号、企业微信都不作为控制面的唯一依赖。
6. 默认降级不要求认证服务号：邮件、Web Push/应用内通知、一次性链接即可工作。

【事实】个人订阅号无法通过微信认证；官方帮助明确“个人类型公众号/服务号暂时不支持微信认证”（[微信认证后有哪些特权](https://kf.qq.com/faq/1612197nEJNR161219BB7Jne.html)）。

【事实】公众号能力受账号类型严格限制：

- 生成带参数二维码接口明确只支持“服务号（仅认证）”（[生成带参数的二维码](https://developers.weixin.qq.com/doc/service/api/qrcode/qrcodes/api_createqrcode)）。
- 网页授权明确只支持已认证服务号，另对已认证政府、事业单位、媒体类型公众号有特殊补充（[微信网页授权](https://developers.weixin.qq.com/doc/service/guide/h5/auth.html)）。
- 发送客服消息、发送订阅通知等主动接口标注“仅认证”，且说明仅允许企业主体已认证账号调用（[发送客服消息](https://developers.weixin.qq.com/doc/service/api/customer/message/api_sendcustommessage.html)、[发送订阅通知](https://developers.weixin.qq.com/doc/service/api/notify/notify/api_sendnewsubscribemsg)）。

【推断】因此，“个人订阅号 + 扫码关注 + 网页授权 + 主动通知”不能作为 Nova 的通用远程控制方案。即便有认证服务号，消息仍受 5 秒被动回复、48 小时客服窗口、模板/订阅通知准入、公网回调和平台非端到端加密等约束，不适合作为唯一控制面。

【事实】微信/企业微信的回调加密是“平台到开发者服务器”的出站消息加密，官方文档没有宣称端到端加密（E2EE）。【推断】消息在到达开发者前要由微信/企业微信平台接收和路由，因此不能把微信消息、企业微信消息视为“只有手机用户与本地 Agent 可读”的端到端加密通道。

【建议】任何微信/企业微信消息都不传 API Key、设备私钥、访问令牌、完整私有源码、客户数据或未脱敏日志；只传任务标识、状态摘要和一次性工作台链接。

---

## 1. 账号、主体与能力边界

### 1.1 三类主体不要混为一谈

| 通道/主体 | 开通条件 | 可作为手机绑定入口 | 可接收远程指令 | 可主动发完成通知 | 对 Nova 的定位 |
|---|---|---|---|---|---|
| 个人订阅号（现文档称“公众号”） | 个人主体，不可微信认证【事实】 | 不能使用公众号参数二维码【事实】；只能用普通 URL 二维码/链接【建议】 | 可配置消息回调并被动回复，但需以账号后台权限为准【推断】 | 不能使用客服/模板/订阅通知等主动接口【事实】；因此无法做异步完成通知【推断】 | 仅可作为“微信内浏览器入口”，不能作为控制面 |
| 认证服务号 | 个人暂不支持认证【事实】；认证通常 300 元/次、有效期 1 年，部分组织免费【事实】（[微信认证后有哪些特权](https://kf.qq.com/faq/1612197nEJNR161219BB7Jne.html)）；因此服务号需为可认证主体【推断】 | 参数二维码、网页授权可用【事实】 | 消息/事件回调可用，但受 5 秒/重试/公网 URL 约束【事实】 | 客服消息、模板消息、订阅通知可用，但各有准入和限额【事实】 | 可选通知/身份适配层，不做主路径 |
| 认证的公众号（原订阅号，非个人主体） | 认证后可能获得部分开发接口【事实】 | 参数二维码、网页授权仍不支持，除非属于特殊政府/媒体网页授权例外【事实】 | 具体以各接口适用表为准【未核实】 | 客服/订阅通知存在“公众号仅认证”的接口表表述，但与产品介绍存在差异【未核实】 | 不建议作为方案基础 |
| 企业微信自建应用 | 企业管理员创建；成员需在应用可见范围内【事实】 | 可用企业微信身份/OAuth，但面向企业内部成员【事实】 | 可接收成员发给应用的消息并被动回复【事实】 | 可发送应用消息【事实】 | 企业内部可选通道 |
| 企业微信群机器人/消息推送 | 企业微信群内创建 webhook【事实】 | 不适用 | 官方消息推送文档只定义出站 POST【事实】；官方社区答复称不支持接收消息，正式文档未确认【未核实】 | 可单向推送，20 条/分钟【事实】 | 仅团队通知适配 |
| 通用手机 Web 工作台 | 自有域名、TLS、中继和账号体系【建议】 | 普通二维码/一次性链接即可，无需微信账号【建议】 | 通过中继到本地，完全自控【建议】 | Web Push/邮件/应用内通知【建议】 | **推荐主路径** |

【事实】当前官方文档已经把“原公众号（包含订阅号与服务号）”拆分为“公众号（原订阅号）”和“服务号”两套文档（[UnionID 机制说明](https://developers.weixin.qq.com/doc/subscription/guide/product/unionid.html)）。本文使用“个人订阅号/认证服务号”时，分别指普通订阅号主体和已认证服务号。

### 1.2 认证并不等于所有接口都开放

【事实】官方帮助把认证后的能力概括为：公众号（订阅号）可使用部分开发接口；服务号可使用全部高级开发接口；个人类型公众号/服务号暂不支持微信认证（[微信认证后有哪些特权](https://kf.qq.com/faq/1612197nEJNR161219BB7Jne.html)）。

【推断】“认证订阅号有部分接口”不能推导出参数二维码、网页授权、客服消息、模板消息或订阅通知一定可用；每一项都必须看该接口的“适用范围”和账号后台。Nova 不应基于“订阅号已认证”做产品假设。

---

## 2. 公众号通道逐项核实

### 2.1 扫码关注与带参数二维码

【事实】生成带参数二维码接口必须在服务器端调用，不可在前端直接调用；临时二维码有效期最长 30 天（2,592,000 秒），永久二维码无过期时间但最多 10 万个；该接口“支持「服务号（仅认证）」账号类型调用”（[生成带参数的二维码](https://developers.weixin.qq.com/doc/service/api/qrcode/qrcodes/api_createqrcode)）。

【事实】用户扫描带场景值二维码时：

- 未关注公众号：用户关注后，微信推送带场景值的关注事件；`Event=subscribe`，`EventKey` 为 `qrscene_` 前缀加场景值，并带 `Ticket`。
- 已关注公众号：微信推送扫描事件；`Event=SCAN`，`EventKey` 为场景值，并带 `Ticket`。
- 事件中的 `FromUserName` 是用户对该公众号的 OpenID。

以上来自（[接收事件推送](https://developers.weixin.qq.com/doc/service/guide/product/message/Receiving_event_pushes.html)）；二维码类型与临时/永久含义同见二维码接口页。

【事实】二维码图片可由 `ticket` 换取，换取接口不要求登录态，`ticket` 需要 URL 编码（[生成带参数的二维码](https://developers.weixin.qq.com/doc/service/api/qrcode/qrcodes/api_createqrcode)）。

【推断】`OpenID` 只是“用户对该公众号的标识”，不是强认证凭证。扫码事件可以证明“某个微信账号扫了这个码”，但不能单独证明“该用户就是 Nova 的合法控制者”。如果二维码被转发、截图或抢扫，仅凭 OpenID 建立控制关系是不安全的。

【建议】如果未来确实支持认证服务号的可选绑定：

- 临时二维码在业务层再限制为 5 分钟，单次使用，服务端只保存 token 哈希；
- 场景值使用高熵随机值，不包含用户 ID、设备 ID 或任何秘密；
- 扫码事件只作为“候选绑定”，必须回到本地桌面确认设备名称/短验证码后才生效；
- 不把永久二维码用于多设备绑定；
- 扫码前已关注和未关注都要处理 `SCAN` 与 `subscribe` 两种事件；
- 事件处理按 `FromUserName + CreateTime` 去重（事件无 `MsgId`），并使用幂等状态机。

【事实】个人订阅号不能调用该接口，因为接口适用表明确只支持认证服务号；因此不能把“扫码关注”作为个人项目的通用绑定方案。

### 2.2 网页授权、OpenID 与 UnionID

【事实】网页授权只支持已认证服务号；其他类型账号，包括部分公众号、小程序、网站应用、移动应用，除已认证服务号之外均不支持微信网页授权登录。特殊补充：已认证的政府、事业单位和媒体类型公众号也有权限（[微信网页授权](https://developers.weixin.qq.com/doc/service/guide/h5/auth.html)）。

【事实】网页授权仅有两个 scope：

- `snsapi_base`：静默授权，直接跳转，只能获取用户 OpenID，不能获取昵称头像；
- `snsapi_userinfo`：弹出授权页，用户同意后可通过 OpenID 获取用户基本信息，即使未关注服务号也可获取。

来源同上。

【事实】`code` 只能使用一次，5 分钟未使用自动过期；授权 `access_token` 示例有效期为 7,200 秒，`refresh_token` 有效期为 30 天；服务号 `secret` 和授权 `access_token` 必须只保存在服务器，不允许传给客户端（[微信网页授权](https://developers.weixin.qq.com/doc/service/guide/h5/auth.html)）。

【事实】网页授权域名配置要求：

- 只有已认证服务号，或部分已认证政府、媒体类型公众号能看到该配置；
- 每个已认证服务号最多配置 2 个网页授权域名，每月最多修改 5 次；
- 只支持 HTTPS，不支持 IP；
- 域名需经过 ICP 备案，新备案域名需 24 小时后配置；
- 需在域名根目录放置校验文件并可访问。

来源：[域名管理](https://developers.weixin.qq.com/doc/oplatform/developers/basic_func/domain.html)。

【事实】OpenID 是“微信用户 + 公众号 AppID”；UnionID 是“微信用户 + 开放平台账号”。同一用户对不同公众号的 OpenID 不同；只有把公众号绑定到同一微信开放平台账号后，UnionID 才能用于跨应用统一身份。网页授权页还说明，`unionid` 仅在 `scope=snsapi_userinfo` 时返回（[UnionID 机制说明](https://developers.weixin.qq.com/doc/subscription/guide/product/unionid.html)、[微信网页授权](https://developers.weixin.qq.com/doc/service/guide/h5/auth.html)）。

【推断】Nova 当前只有单机 Agent 和单个用户时，不需要 UnionID。引入 UnionID 只会增加平台绑定、隐私和账号迁移成本；如果未来做独立移动端、Web 和公众号多端统一，再评估是否绑定开放平台。

【建议】手机工作台不要依赖公众号网页授权，也不要让用户为了登录而关注公众号。微信内打开时，工作台仍使用 Nova 自己的账号/设备绑定；网页授权最多作为可选的“绑定已有认证服务号身份”适配器。

### 2.3 文本与事件回调、签名和加密

【事实】公众号消息推送配置需要 URL、Token、EncodingAESKey；URL 必须以 `http://` 或 `https://` 开头，分别支持 80 和 443 端口；Token 用于签名；EncodingAESKey 用于消息体加解密；加解密方式有明文、兼容、安全三种，安全模式为纯密文，官方强烈推荐（[消息与事件推送介绍](https://developers.weixin.qq.com/doc/service/guide/dev/push/)）。

【事实】配置保存后，微信会向 URL 发送 GET 验证请求，携带 `signature`、`timestamp`、`nonce`、`echostr`；开发者需按 Token、timestamp、nonce 字典序排序、拼接并 SHA1，与 `signature` 比对，成功则原样返回 `echostr`（同上）。

【事实】文本消息以 XML POST 到开发者 URL，包含 `ToUserName`、`FromUserName`、`CreateTime`、`MsgType=text`、`Content`、`MsgId` 等；`FromUserName` 是 OpenID（[接收普通消息](https://developers.weixin.qq.com/doc/service/guide/product/message/Receiving_standard_messages)）。

【事实】安全模式下，推送 URL 增加 `encrypt_type=aes` 和 `msg_signature`；签名算法为 Token、timestamp、nonce、Encrypt 四者字典序排序后 SHA1；消息体使用 `EncodingAESKey` 进行 AES-256-CBC 解密，PKCS#7 填充，明文结构含 16 字节随机串、4 字节长度、消息体和 AppID。官方明确提醒：安全模式不要使用 `signature` 验证，而应使用 `msg_signature`（[消息加解密说明](https://developers.weixin.qq.com/doc/service/guide/dev/push/encryption.html)）。

【未核实】回调数据格式存在官方文档冲突：

- “消息与事件推送介绍”写“数据格式：消息体的格式，仅支持 XML”（[链接](https://developers.weixin.qq.com/doc/service/guide/dev/push/)）。
- 同站点“公众号与服务号”产品介绍写“数据格式：支持 XML 和 JSON”（[链接](https://developers.weixin.qq.com/doc/oplatform/developers/product/subscription_service/)）。
- “消息加解密说明”同时给出 JSON 示例并写“假设数据格式为 JSON”（[链接](https://developers.weixin.qq.com/doc/service/guide/dev/push/encryption.html)）。

【推断】不要把“只支持 XML”或“支持 JSON”写成绝对事实；实现时按账号实际推送格式兼容 XML，JSON 能力必须用目标账号验证。

【建议】如果未来接入公众号回调，中继必须：

- 在公网 HTTPS 端点上完成原始请求验签、安全模式验签、解密、时间戳窗口和重放检查；
- 把事件转为内部最小化事件，不把原始 XML/JSON 直接转发到本地；
- 用 `MsgId` 对普通消息去重，用 `FromUserName + CreateTime` 对事件去重；
- 回调处理保持短事务，不在 webhook 内执行长任务；
- 为公众号配置独立密钥和最小权限账号，密钥不进入源码或本地客户端。

### 2.4 被动回复

【事实】微信服务器把用户消息发给开发者服务器后，5 秒内收不到响应会断开连接并重发，总共重试 3 次；有 `MsgId` 的消息推荐用 `MsgId` 排重，事件推荐用 `FromUserName + CreateTime` 排重；无法在 5 秒内处理时，应回复 `success`（推荐）或空字符串，微信不会重试；之后可使用客服消息接口异步回复（[被动回复用户消息](https://developers.weixin.qq.com/doc/service/guide/product/message/Passive_user_reply_message.html)）。

【事实】如果 5 秒内没有回复任何内容，或回复了 JSON 等异常数据，微信会向用户显示“该服务暂时无法提供服务”一类系统提示（同上）。

【事实】启用服务器配置后，用户消息将转发至该地址，公众号后台设置的自动回复和自定义菜单将失效（[消息与事件推送介绍](https://developers.weixin.qq.com/doc/service/guide/dev/push/)）。运营上需注意。

【推断】公众号不能可靠地“在回调里跑完一个长任务再回复”。Nova 只能先 ack，再把任务放入本地队列；完成通知则受客服消息时限、模板/订阅通知准入限制，不能假设一定能主动送达。

### 2.5 客服消息时限与额度

【事实】当用户与公众号产生特定动作时，开发者可以在“目前为 48 小时”内调用客服接口发送消息；允许的动作包括用户发送信息、点击特定菜单、关注公众号、扫描二维码（[发送客服消息](https://developers.weixin.qq.com/doc/service/api/customer/message/api_sendcustommessage.html)）。

【事实】客服消息下发额度：

| 触发动作 | 下发额度 | 额度有效期 |
|---|---:|---:|
| 用户发送消息 | 5 条 | 48 小时 |
| 点击自定义菜单（仅部分菜单类型） | 3 条 | 1 分钟 |
| 关注公众号 | 3 条 | 1 分钟 |
| 扫描二维码 | 3 条 | 1 分钟 |

来源：[发送客服消息](https://developers.weixin.qq.com/doc/service/api/customer/message/api_sendcustommessage.html)、[客服消息介绍](https://developers.weixin.qq.com/doc/service/guide/product/kf/intro.html)。

【事实】该接口适用范围标注“公众号：仅认证；服务号：仅认证”，并解释“仅认证”表示仅允许企业主体已认证账号调用，未认证或不支持认证的账号无法调用（[发送客服消息](https://developers.weixin.qq.com/doc/service/api/customer/message/api_sendcustommessage.html)）。

【推断】个人订阅号无法认证，因此不能使用客服消息做异步完成通知；它只能在用户发消息后的被动回复窗口内回应，无法支撑“任务几小时后完成再通知手机”的主流程。

【建议】即使使用认证服务号，客服消息也只作为“用户刚互动过”的短窗口补充通知，不作为唯一完成通知；完成通知应优先走工作台自己的 Web Push/邮件/应用内通知。

### 2.6 模板消息与订阅通知

#### 模板消息

【事实】模板消息仅用于服务号向用户发送重要服务通知，不支持广告营销等可能骚扰用户的消息；所有服务号能看到申请入口，但只有认证后的服务号才能申请并获得权限；每个服务号最多 5 个类目、每月最多修改 5 次、可同时使用 25 个模板；当前每个账号日调用上限为 10 万次，粉丝规模达到更高量级时上限会提升，以后台为准（[模板消息](https://developers.weixin.qq.com/doc/service/guide/product/template_message/Template_Message_Interface.html)）。

【事实】该页面当前仍写“模板消息能力可正常使用”，并写订阅通知功能处于灰度测试；因此不能依据二手文章断言模板消息已在所有账号下线（同上）。

【推断】模板消息仍受“认证服务号”“服务通知场景”“类目/模板审核”和日限额约束，不适合作为任意 Agent 事件的通用推送总线；合规风险也高于自有工作台通知。

#### 订阅通知

【事实】订阅通知是“用户主动订阅、认证服务号按需下发”的能力；一次性订阅是用户订阅一次、认证服务号可不限时间下发一条对应通知；长期订阅是订阅一次后可长期多次下发，仅向政务民生、医疗等公共服务领域开放；开通需要认证服务号、行业类目和公共模板库模板（[订阅通知介绍](https://developers.weixin.qq.com/doc/service/guide/product/subscription_messages/intro.html)）。

【事实】订阅通知的适用主体存在官方表述差异：

- 介绍页反复写“认证服务号”；
- 发送订阅通知接口的适用表同时列“公众号：仅认证”“服务号：仅认证”，并解释“仅认证”只允许企业主体已认证账号调用（[发送订阅通知](https://developers.weixin.qq.com/doc/service/api/notify/notify/api_sendnewsubscribemsg)）。

【推断】个人订阅号无论如何都不能使用订阅通知；认证服务号可以使用，但具体“公众号（原订阅号）”是否可用要以账号后台和接口返回为准。不能根据产品介绍页把认证订阅号纳入默认能力。

【事实】订阅通知事件推送会包含用户同意/拒绝状态、模板 ID 和弹窗场景；官方示例为 XML（[订阅通知的事件推送](https://developers.weixin.qq.com/doc/service/guide/product/subscription_messages/push.html)）。由于回调数据格式本身存在文档冲突，实际格式仍需按账号验证。

【建议】订阅通知最多作为用户明确订阅后的补充完成通知，不能作为远程指令通道，不能承载密钥、源码或完整审批内容；通知内容只放任务 ID、脱敏标题和一次性工作台链接。

### 2.7 access_token、IP 白名单、公网 HTTPS 与 ICP

【事实】获取接口调用凭据（access_token）的有效期为 7,200 秒，需妥善保存；官方推荐使用稳定版接口调用凭据；AppSecret 是账号后台 API 密钥，必须妥善保管；调用 IP 不在白名单会返回 40164（[获取接口调用凭据](https://developers.weixin.qq.com/doc/service/api/base/api_getaccesstoken.html)）。

【事实】公众号/服务号支持 API IP 白名单：仅白名单中的 IP 可调用服务端接口；支持具体 IP 和 IP 段（如 `172.0.0.1/24`），不支持 `172.0.0.*` 和 `IP:端口` 形式；可配置多个；配置路径在微信开发者平台的公众号/服务号基础信息-开发信息；不在白名单调用返回 40164（[API IP 白名单](https://developers.weixin.qq.com/doc/oplatform/developers/basic_func/ip_whitelist.html)）。

【事实】微信提供“获取微信推送服务器 IP”接口，用于获取向开发者服务器推送消息的来源 IP；出口/入口 IP 可能变动，建议每天拉取一次，不要长期写死旧列表（[获取微信推送服务器 IP](https://developers.weixin.qq.com/doc/service/api/base/api_getcallbackip.html)）。

【事实】公众号回调 URL 官方要求以 HTTP 或 HTTPS 开头，分别支持 80/443 端口（[消息与事件推送介绍](https://developers.weixin.qq.com/doc/service/guide/dev/push/)）。

【推断】官方正文没有在该页直接写“公网可达”，但回调是微信服务器主动 POST，实际部署必然要求平台可达；这是工程判断，不是平台原文。

【事实】服务号网页授权域名、JS 接口安全域名、业务域名均要求 HTTPS、ICP 备案、域名归属校验；网页授权域名最多 2 个、JS 安全域名最多 5 个、业务域名最多 3 个，均每月最多修改 5 次（[域名管理](https://developers.weixin.qq.com/doc/oplatform/developers/basic_func/domain.html)）。

【未核实】公众号“消息回调 URL”页面本身没有明确写 ICP 备案要求；不能把网页授权域名的 ICP 规则直接套到任意回调域名上。若回调与网页授权/JS 安全域名同域，则实际会受相应域名规则约束；若使用独立域名，请以账号后台和接入商要求为准。

【建议】不要从本地桌面直接调用公众号 API：家庭/办公公网出口 IP 经常变化，无法稳定加入 API IP 白名单。若未来使用认证服务号，应由固定出口 IP 的中继保管 AppSecret、换取 access_token、接收回调；本地 Agent 不保存公众号密钥。

【推断】在中国大陆自建公网服务通常还涉及 ICP 备案和接入商要求；这是部署合规问题，不是微信接口独有的技术限制。具体以服务器所在地监管和接入商要求为准。

### 2.8 公众号路线结论

【建议】公众号只在同时满足以下条件时作为可选适配器：

- 用户已拥有可完成微信认证的服务号（个人类型暂不支持认证）；
- 已完成网页授权/JS 安全域名的 HTTPS + ICP + 归属校验；
- 有稳定公网回调 URL 和固定 API 出口 IP；
- 已接受 5 秒被动回复、48 小时客服窗口、模板/订阅通知审核与限额；
- 已接受消息内容不视为 E2EE。

【推断】对于个人项目、没有认证服务号的用户，公众号路线无法完成“安全绑定 + 主动完成通知 + 可撤销远程审批”的闭环。它最多能提供：

- 用户主动发消息后的被动回复；
- 一个“在微信里打开工作台”的入口（普通 URL 二维码，不依赖公众号参数二维码）。

---

## 3. 企业微信通道

### 3.1 自建应用

【事实】企业管理员可在管理后台“应用管理-自建应用”创建应用，填写 Logo、名称、介绍和可见范围；可见范围可在管理后台或手机端设置；应用负责人默认拥有发送消息、接收消息权限（[如何创建/设置自建应用权限](https://open.work.weixin.qq.com/help2/pc/16892)、[企业自建应用](https://open.work.weixin.qq.com/wwopen/manual/detail?t=selfBuildApp)）。

【事实】自建应用可以发送文本、图片、视频、文件、图文、Markdown、模板卡片等应用消息；文本内容最长 2048 字节；消息接口为 `POST https://qyapi.weixin.qq.com/cgi-bin/message/send?access_token=ACCESS_TOKEN`（[发送应用消息](https://developer.work.weixin.qq.com/document/path/90236)）。

【事实】应用消息频率限制：

- 每应用不超过“账号上限数 × 200 人次/天”；
- 每应用对同一成员不超过 30 次/分钟、1000 次/小时；
- 超过部分会被丢弃。

接收人不在应用可见范围时，会返回无效接收人；全部无效时返回失败（[发送应用消息](https://developer.work.weixin.qq.com/document/path/90236)）。

【事实】自建应用接收消息需要配置回调 URL、Token、EncodingAESKey；URL 必须公开可访问；企业微信先发 GET 请求验证，服务端需在 1 秒内返回解密后的明文，不能带引号、BOM 或换行；后续 POST 推送加密消息；企业微信 5 秒内收不到响应会断开并重试，总共重试 3 次，建议先应答再异步处理（[回调配置](https://developer.work.weixin.qq.com/document/path/90930)）。

【事实】企业微信回调消息使用 AES 加密，EncodingAESKey 固定 43 个字符，AES-256-CBC、PKCS#7 填充；签名使用 Token、timestamp、nonce、密文计算 SHA1（[加解密方案说明](https://developer.work.weixin.qq.com/document/path/90968)）。

【事实】自建应用接收的文本消息包含 `ToUserName`（企业 CorpID）、`FromUserName`（成员）、`CreateTime`、`MsgType=text`、`Content`、`MsgId`、`AgentID`（[消息格式](https://developer.work.weixin.qq.com/document/path/90239)）。

【事实】2022-06-20 20 点之后新创建的自建应用必须配置“可信 IP”，仅配置的 IP 能调用接口；不支持 IP 段、含 `*` 的 IP，需填公网 IPv4，多个用英文分号分隔，每个应用最多 120 个（[可信IP说明](https://open.work.weixin.qq.com/help2/pc/21711)）。

【事实】企业微信 JS-SDK 要求所有 JS 接口在应用可信域名（含子域名）下调用，且可信域名必须有 ICP 备案并在管理端验证域名归属（[开始使用](https://developer.work.weixin.qq.com/document/path/98416)）。

【未核实】企业微信“回调配置”页要求 URL 公开可访问，但该页没有明确写回调域名必须 ICP 备案或必须是域名；ICP 的明确要求出现在可信域名（用于 JS-SDK/网页能力）文档中。若把回调 URL 与可信域名同域，通常受相应域名规则约束；独立回调 URL 的具体要求需以企业微信后台和接入商为准。

【事实】企业微信网页授权支持 `snsapi_base`（静默，获取成员 UserID）和 `snsapi_privateinfo`（手动授权，获取头像、二维码等敏感信息，要求成员在应用可见范围内）；`agentid` 在敏感授权时必填（[构造网页授权链接](https://developer.work.weixin.qq.com/document/path/91022)）。

【事实】企业微信 access_token 有效期正常为 7,200 秒，每个应用独立；官方要求缓存，不能频繁调用 `gettoken`，且不能把 access_token 返回给前端（[获取access_token](https://developer.work.weixin.qq.com/document/path/91039)）。

【事实】企业微信提供接口 IP 段和回调 IP 段查询，IP 段可能变化，新旧段会并行保留一段时间；用于防火墙时建议每天定时拉取（[获取企业微信接口IP段](https://developer.work.weixin.qq.com/document/path/92520)、[获取企业微信回调IP段](https://developer.work.weixin.qq.com/document/path/92521)）。

【推断】企业微信自建应用适合“企业团队内部的 Nova 远程审批”，但不适合普通个人用户：需要企业管理员、企业成员身份、应用可见范围、可信 IP 和公网回调；并且消息仍由平台处理和存储，不是 E2EE。

### 3.2 群机器人/消息推送

【事实】企业微信“消息推送（原群机器人）”通过 webhook URL 接收开发者的 POST：支持文本、Markdown、图片、图文、文件、语音、模板卡片等；文本最长 2048 字节，Markdown 最长 4096 字节；每个消息推送不超过 20 条/分钟；webhook 地址应妥善保护，泄露后可被用来发垃圾消息（[消息推送配置说明](https://developer.work.weixin.qq.com/document/path/91770)）。

【事实】该官方文档只描述“开发者向 webhook POST”的出站方向，没有提供群机器人接收消息或回调的配置项。

【事实】企业微信官方社区答复多次表示“群机器人不支持接收消息/不支持被动回调”（[官方社区示例](https://developer.work.weixin.qq.com/community/question/detail?content_id=16664416507037376612)）。

【未核实】该结论来自官方支持答复而非正式接口文档；若要把“群机器人”用于双向控制，必须由企业微信后台/支持再次确认。

【建议】群机器人只用于单向完成通知，且仅发送脱敏摘要。webhook key 视作 bearer secret，放在中继的密钥管理中，不要进入客户端或日志；机器人所在群应限制成员。

### 3.3 企业微信智能机器人

【事实】智能机器人开启 API 模式后，企业微信向配置的 URL 推送消息和事件；接收消息与被动回复均需加密，需经过 URL 有效性验证，Token/EncodingAESKey 要妥善保管（[智能机器人概述](https://developer.work.weixin.qq.com/document/path/101039)）。

【推断】智能机器人可作为企业微信内“群聊@或单聊”的可选交互入口，比群机器人更接近双向控制；但它仍依赖企业微信平台、企业配置和回调公网 URL，不应成为 Nova 的唯一控制面。

---

## 4. 通用手机 Web 工作台

### 4.1 架构与协议

【事实】WebSocket 是 RFC 6455 定义的全双工协议；Server-Sent Events（SSE）在 WHATWG HTML 标准中定义，是服务器到浏览器的单向事件流，支持自动重连和 `Last-Event-ID` 恢复（[RFC 6455](https://www.rfc-editor.org/rfc/rfc6455)、[HTML SSE](https://html.spec.whatwg.org/multipage/server-sent-events.html)）。

【建议】手机工作台优先使用：

- HTTPS 提供 H5/PWA；
- WSS（WebSocket over TLS）承载进度和审批事件；
- 若网络环境不适合 WebSocket，降级为 HTTPS + SSE 接收事件、HTTPS POST 发送命令；
- 传输层至少 TLS 1.2+，优先 TLS 1.3（[RFC 8446](https://www.rfc-editor.org/rfc/rfc8446)）。

【建议】工作台是普通 HTTPS 页面，不依赖微信 OAuth、公众号 JS-SDK 或企业微信 JS-SDK。手机微信扫一扫只负责“打开 HTTPS 链接”；真正身份由 Nova 自己的绑定和设备密钥完成。该“微信内打开网页”的能力是产品假设/建议，不是微信公众平台接口承诺。

### 4.2 身份、绑定与通知

【建议】身份与绑定：

- 桌面端生成一次性绑定会话，含高熵随机 token、本地临时公钥和短验证码；
- 手机打开链接后生成设备密钥对，公钥经中继注册；
- 桌面与手机显示同一短验证串（SAS），由用户核对后确认，防止中继替换公钥；
- 绑定成功后，手机私钥只保存在平台安全存储/不可导出密钥中；
- 默认只授予只读进度；审批/控制权限需单独授权；
- 支持“撤销此设备”和“撤销全部设备”。

【建议】认证方式：

- 首推 WebAuthn/passkey，避免密码和短信验证码（[W3C WebAuthn](https://www.w3.org/TR/webauthn-3/)）；
- 或一次性邮件 magic link + 短期会话；
- 不把微信号、手机号或 OpenID 当作唯一认证因子；
- 高价值操作要求再次生物识别/设备解锁（step-up）。

【事实】微信开放平台的“网站应用微信登录”与公众号网页授权不是同一能力：接入前要有已审核通过的网站应用并申请微信登录且通过审核；PC 端使用 `qrconnect`，`scope=snsapi_login`，用户扫码授权后回调携带 `code`；`code` 超时时间为 10 分钟，一个 `code` 只能成功换取一次 access_token。网站应用授权回调域名最多 1 个，每月最多修改 5 次；网站应用需审核通过后才能编辑该配置（[网站应用微信登录开发指南](https://developers.weixin.qq.com/doc/oplatform/Website_App/WeChat_Login/Wechat_Login.html)、[网站应用](https://developers.weixin.qq.com/doc/oplatform/developers/product/webapp/)）。

【未核实】网站应用授权回调域名的官方限制段没有像“业务域名”那样明确写 ICP 备案；微信登录流程本身还涉及开放平台开发者资质与网站应用审核。不能把公众号网页授权域名规则直接套到网站应用回调域。

【建议】网站应用微信登录只适合“PC 管理台扫码登录”，不是手机工作台的绑定方案；Nova 的手机绑定不应依赖它。若未来做 Web 管理台并希望用微信身份，应作为可选 SSO，不要替代设备密钥和本地审批。

【建议】通知：

- 首推应用内通知中心 + Web Push；Web Push 协议见 [RFC 8030](https://www.rfc-editor.org/rfc/rfc8030)，消息加密见 [RFC 8291](https://www.rfc-editor.org/rfc/rfc8291)；
- 邮件作为通用降级；邮件只发任务 ID/状态和一次性链接，不发敏感内容；
- Web Push 在目标手机、浏览器、微信内置浏览器上的可用性【未核实】，必须实测；微信内置浏览器可能无法安装 PWA 或接收推送，应提供“在系统浏览器打开”的路径；
- 若没有任何推送能力，只能靠工作台轮询/应用内通知，不能宣称实时主动通知。

---

## 5. 三种架构对比

### 5.1 总表

| 维度 | 公众号消息回调（个人订阅号） | 公众号消息回调（认证服务号） | 企业微信自建应用 | 企业微信消息推送/群机器人 | 通用手机 Web 工作台 |
|---|---|---|---|---|---|
| 最低前置条件 | 注册个人订阅号并配置服务器；不可认证 | 可完成认证的服务号主体、公网回调、域名/ICP；启用 API IP 白名单时需稳定出口 IP | 企业、管理员、成员可见范围、公网回调、可信 IP | 企业微信群 + webhook | 域名、TLS、中继、账号体系 |
| 手机扫码绑定 | 不能使用参数二维码【事实】；只能普通 URL 二维码【推断】 | 参数二维码可用【事实】 | 企业身份/OAuth；非企业成员不可用【事实】 | 不适用 | 普通一次性二维码/链接【建议】 |
| 接收文本指令 | 可配置回调/被动回复，具体以后台为准【推断】 | 可【事实】 | 可【事实】 | 官方未提供入站接收【事实】；社区称不支持【未核实】 | 可，自有通道【建议】 |
| 主动完成通知 | 不能使用模板/订阅通知【事实】；不能做异步客服通知【推断】 | 客服 48h、模板/订阅通知准入与限额【事实】 | 应用消息，有频率限制【事实】 | 单向推送，20 条/分钟【事实】 | Web Push/邮件/应用内【建议】 |
| 长任务体验 | 5 秒被动回复窗口【事实】；难异步【推断】 | 5 秒 ack 后异步【推断】；主动通知受限【事实】 | 可先应答后异步；回调有 5 秒/3 次重试【事实】 | 仅通知，不参与执行【事实】 | 原生支持长任务状态流【建议】 |
| 身份安全 | OpenID 非强凭证【推断】；无网页授权【事实】 | OpenID/UnionID + 网页授权，但需自建会话【事实】 | 企业成员 UserID，边界清晰【事实】 | webhook key 泄露即可发消息【事实】 | 可做 passkey + 设备密钥【建议】 |
| 撤销与审计 | 只能自建，平台帮助有限【推断】 | 自建 + 平台事件；平台侧审计有限【推断】 | 企业管理员可停用应用/移除可见范围【事实】 | 只能轮换/删除 webhook【推断】 | 设备级撤销、双份审计【建议】 |
| 端到端加密 | 否【推断】 | 否【推断】 | 否【推断】 | 否【推断】 | 可做应用层 E2EE【建议】 |
| 个人项目适用性 | 低：不能主动通知，不能参数二维码 | 成本/门槛高，仍受限 | 不适用（需企业） | 仅团队通知 | **高** |
| 结论 | 仅微信内浏览器入口 | 可选通知/身份适配，不做主路径 | 企业内部可选 | 仅单向通知 | **推荐主路径** |

### 5.2 公众号路线的关键短板

1. 【事实】个人订阅号不能认证，且不能使用参数二维码、网页授权、客服消息、模板消息、订阅通知；【推断】因此不能把公众号作为控制面。
2. 【事实】认证服务号需要公网回调；若启用 API IP 白名单，还需要稳定出口 IP；网页授权/JS 域名要求 HTTPS+ICP。【推断】对本地优先的桌面 Agent 来说，等于增加一套对公服务和运维面。
3. 【事实】被动回复只有 5 秒；异步主动通知受 48 小时客服窗口或模板/订阅通知准入限制。
4. 【推断】微信回调加密不是 E2EE；消息内容和元数据对平台可见。
5. 【事实】启用服务器配置会使用户消息转发到该 URL，后台自动回复和自定义菜单失效，运营影响明显。

### 5.3 企业微信路线的关键短板

1. 【事实】自建应用只面向企业成员，需要管理员、可见范围和可信 IP；不适合个人消费者。
2. 【事实】正式文档只提供出站消息推送；【未核实】官方社区答复称不支持入站；【推断】因此不能把群机器人作为双向控制面。
3. 【推断】企业微信同样不是 E2EE；消息内容和元数据对企业微信平台可见。

### 5.4 手机 Web 工作台的优势

1. 【建议】不依赖微信账号类型，个人项目可用。
2. 【建议】本地不暴露端口，只做主动出站。
3. 【建议】可以完整呈现进度、diff 摘要、审批卡片和审计记录，不受 5 秒/48 小时限制。
4. 【建议】可在应用层做端到端加密，中继只转发密文。
5. 【建议】微信只是扫码/浏览器入口，不绑定产品命脉。

---

## 6. Nova 推荐架构

### 6.1 原则

1. **手机工作台优先**：所有核心能力由 Nova 自己的工作台提供；微信/企业微信是可选适配层。
2. **本地零入站**：本地 Agent 不开放公网监听端口，只主动出站到中继。
3. **一次性绑定**：扫码链接短时、单次、需本地确认；不把二维码当长期密钥。
4. **设备密钥**：手机生成密钥，命令签名；中继不能代替设备签名。
5. **应用层 E2EE**：即使中继或 CDN 终止 TLS，也不应看到命令/进度明文。
6. **本地权限引擎是唯一执行者**：远程指令只映射为有限意图，危险操作仍需本地审批。
7. **可撤销、限时、可审计**：每台设备、每个会话、每条命令都有生命周期和审计记录。
8. **数据最小化**：微信/企业微信消息不传密钥、私有源码和未脱敏日志。

### 6.2 组件与数据流

```text
┌─────────────────────┐          HTTPS + WSS/SSE          ┌──────────────────────┐
│ 手机工作台 H5/PWA    │ ────────────────────────────────▶ │ 受控中继              │
│ - 进度/审批/停止     │      （应用层 E2EE 信封）          │ - TLS/静态资源        │
│ - 设备私钥           │ ◀──────────────────────────────── │ - 会话与设备注册      │
└─────────────────────┘                                   │ - 密文路由/推送       │
                                                          │ - 可选微信/企微适配   │
                                                          └──────────┬───────────┘
                                                                     │
                                              本地仅主动出站 mTLS WSS 443
                                                                     │
                                                          ┌──────────▼───────────┐
                                                          │ Nova 本地 Agent       │
                                                          │ - 出站连接器          │
                                                          │ - 权限/审批引擎       │
                                                          │ - 审计日志            │
                                                          │ - 脱敏进度源          │
                                                          └──────────────────────┘

可选：微信扫一扫/认证服务号/企业微信 ──仅入口或通知──▶ 中继适配层
      绝不由微信/企微直接调用本地工具或绕过本地审批
```

### 6.3 一次性绑定流程

【建议】采用“桌面发起 + 手机扫码 + 本地确认 + 短验证串”的流程：

1. 本地 Agent 生成一次性绑定会话：随机 token（至少 128 位）、本地临时密钥对、5 分钟 TTL；中继只持久化 token 哈希，token 原文只出现在本地二维码和手机 URL fragment 中，不写入日志。
2. 本地显示二维码/链接。二维码内容是 Nova 自己的 HTTPS 链接，例如 `https://relay.example/pair#t=...`，与公众号参数二维码无关；链接秘密放在 URL fragment，避免进入服务器 query 日志。
3. 手机扫码打开工作台。手机生成设备密钥对，私钥进入平台安全存储；公钥和一次性 token 提交给中继。
4. 桌面与手机分别根据双方公钥计算短验证串（SAS），用户核对两边一致；本地用户确认设备名称和权限范围。
5. 中继只记录设备 ID、公钥、状态和哈希，不记录私钥；本地也记录同一设备公钥。
6. 绑定成功后，token 立即失效；重复使用、过期、验证串不一致都拒绝；失败次数限流并告警。

【建议】任何“点开链接即自动绑定”的实现都不可接受。一次性链接可能被转发、截屏或被聊天软件预览；必须叠加本地确认和短验证串。扫码绑定不是“微信认证”，只是用摄像头打开 Nova 的页面。

### 6.4 指令、审批与执行

【建议】远程指令只允许有限意图，例如：

- `status.get`：只读进度；
- `run.stop`：停止当前任务（最高优先级、始终允许、幂等）；
- `approval.list`：待审批列表；
- `approval.decide`：同意/拒绝某个待审批动作，必须绑定动作哈希、单次使用、短时有效；
- `run.resume`：仅在本地策略允许的前提下继续已暂停任务；
- `answer.select`：对本地已提出的选择题作答；
- 第二阶段才考虑“追加自然语言指令”，且仍由本地解析、权限引擎审查，不直接进入 shell。

【建议】命令信封：

```text
{
  v: 1,
  command_id: <随机唯一>,
  device_id: <绑定设备>,
  type: <有限意图>,
  action_hash: <审批时绑定原始动作摘要>,
  args_ciphertext: <加密到本地设备公钥>,
  issued_at: <时间>,
  expires_at: <时间，建议 ≤ 60 秒>,
  nonce: <随机>,
  signature: <手机设备私钥签名>
}
```

本地验证：设备已绑定且未撤销、签名有效、时间未过期、nonce 未重放、`action_hash` 与本地待审批动作一致、权限范围允许。任何一项失败都拒绝并审计。

【建议】危险操作策略：

- 本地权限引擎决定“可远程审批 / 只能本地审批 / 直接拒绝”；
- 删除文件、执行任意命令、修改系统配置、访问密钥/凭据、外发源码、支付类操作等高风险动作，一律要求本地设备上的明确确认；
- 手机可以拒绝、查看或批准低/中风险动作，但不能把“危险”降级为“安全”；
- “停止”不需要审批，不能被远程禁用；本地还要有物理/桌面 kill switch；
- 远程审批不能绕过现有 Nova 权限审批链，只能在链上增加一个审批因子。

【建议】审批通知内容只包含：任务 ID、脱敏动作标题、风险等级、过期时间、工作台链接；完整参数只在 E2EE 工作台内查看。审批默认 5 分钟过期，单次使用，绑定具体动作哈希；执行后不可复用。

### 6.5 受控中继与“不暴露本地端口”

【建议】推荐自建/单租户受控中继：

- 部署在用户自有 VPS 或受信云主机，HTTPS/WSS 对外；
- 本地 Agent 仅主动出站 443 建立 mTLS WSS，不监听公网；
- 中继只持久化密文信封、设备公钥、路由状态和最小审计元数据；
- 中继不可见命令/进度明文；即使中继被攻破，也不能直接取得手机私钥。若中继同时托管手机前端，它仍可能篡改 JS 诱导在线设备签名，因此前端静态资源应独立托管并做签名发布/完整性校验，高风险动作始终本地审批；
- 中继具备静态出口 IP，便于将来可选的公众号/企业微信 API 白名单；
- 可选微信/企业微信适配器部署在中继侧，AppSecret 不进入本地。

【事实】Cloudflare Tunnel 使用出站连接模型：`cloudflared` 从源站主动连接 Cloudflare 全球网络，不需要源站有公网可路由 IP，可以阻止所有入站流量；但它的作用是公开/连接源站，不等于应用层鉴权或 E2EE（[Cloudflare Tunnel 文档](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/)）。

【推断】如果使用 Cloudflare 等 CDN/隧道终止 TLS，平台在 TLS 层可以看到明文；因此必须叠加应用层 E2EE，不能只依赖“HTTPS 到中继”。

【建议】比较：

| 方案 | 本地入站端口 | 优点 | 风险/限制 | 结论 |
|---|---|---|---|---|
| 用户自有中继 + 本地出站 WSS | 无 | 控制力强、可做 E2EE、可审计、静态出口 IP | 需运维域名/TLS/主机；大陆主机涉及 ICP | **推荐** |
| 托管中继 | 无 | 运维少 | 需信任服务商；必须 E2EE、最小日志 | 可选，需合同与安全评估 |
| Cloudflare Tunnel 暴露本地 HTTP | 无（但本地 HTTP 被公开） | 快速、无需公网 IP | 暴露的是本地服务面，鉴权/漏配置风险高 | 仅限受控管理入口，不建议作为手机控制主路径 |
| frp/ngrok 等直接端口映射 | 有/等价暴露 | 简单 | 公网攻击面大、IP 漂移、审计弱 | 不推荐 |
| Tailscale/WireGuard 私网 | 无 | 私密、强认证 | 手机需装客户端/VPN，不适合微信内网页 | 仅限管理员备用 |

---

## 7. 安全、隐私与审计

### 7.1 威胁模型

| 威胁 | 影响 | 缓解措施 | 残余风险 |
|---|---|---|---|
| 手机丢失/被盗 | 他人可查看或操作 | 设备撤销、短会话、passkey/生物识别、远程撤销全部、通知脱敏 | 解锁状态下的短窗口 |
| 中继被攻破 | 窃听、篡改、拒绝服务 | 应用层 E2EE、设备签名、中继不存私钥、双份审计、证书校验 | 元数据泄露、可用性 |
| 中继篡改前端代码/供应链 | 恶意页面利用在线设备密钥签名 | 前端静态资源独立源、签名发布/完整性校验、CSP、锁定依赖、最小权限、高风险本地审批 | 已加载恶意代码的短窗口 |
| 恶意二维码/链接 | 攻击者抢先绑定 | 短 TTL、单次使用、本地确认、SAS 核对、限流 | 用户误确认 |
| 命令重放 | 重复执行危险动作 | `command_id` + nonce + `expires_at` + 本地幂等 | 本地实现缺陷 |
| 中继替换公钥（MITM） | 解密/伪造 | 二维码含本地公钥指纹、SAS 双向核对、证书校验 | 用户不核对 |
| 微信/企微账号被盗 | 伪造通知/指令 | 不作为唯一认证；命令需设备签名；通知只提供入口 | 账号内通知被冒发 |
| 本地设备被入侵 | 绕过一切 | 本地权限引擎、OS 密钥保护、最小权限、审计告警 | 本地 root/管理员级攻击 |
| 通知内容泄露 | 源码/密钥外泄 | 永不发送敏感内容；只发 ID/状态/一次性链接；链接短时 | 元数据/任务标题泄露 |

### 7.2 认证、撤销、限时、审计的落地

| 要求 | 建议实现 |
|---|---|
| 可认证 | 设备公钥 + 手机签名 + WebAuthn step-up；中继会话绑定设备；本地再验签；不把 OpenID/微信号当凭证 |
| 可撤销 | 本地“撤销此设备/全部设备”；中继撤销列表；撤销立即阻止新命令；旧会话短 TTL；丢失手机可从中继管理台撤销 |
| 限时 | 绑定 5 分钟；会话短时并轮换；命令 ≤60 秒；审批 ≤5 分钟；所有 token 单次使用 |
| 可审计 | 本地 append-only 审计（命令、审批、执行、结果、撤销）；中继独立审计；哈希链/签名防篡改；记录最小化 |
| 防重放 | nonce + command_id + 过期时间 + 本地幂等表；旧命令不因重连而重放 |
| 离线安全 | 本地断网时不执行中继积压命令；命令过期即丢弃；恢复后只同步状态 |
| 最小权限 | 默认只读；审批/控制单独授权；设备可只授予“状态+停止” |
| 密钥保护 | 手机用不可导出密钥/系统安全存储；桌面用 OS 凭据保护；中继用 KMS/密钥管理；不入库明文、不入日志 |

【建议】审计字段至少包括：事件 ID、设备 ID、操作者、命令类型、动作哈希、权限决策、审批人/时间、执行结果、前后状态、策略版本。不要把源码、完整命令输出、环境变量、令牌写入审计。保留期与导出策略由用户配置。

### 7.3 微信消息不是端到端加密

【事实】微信安全模式使用 `EncodingAESKey` 对回调消息体做 AES-256-CBC 加解密，并使用 Token/时间戳/随机数/密文生成签名（[消息加解密说明](https://developers.weixin.qq.com/doc/service/guide/dev/push/encryption.html)）；企业微信同样使用 EncodingAESKey 和 AES 对回调/回复加密（[加解密方案说明](https://developer.work.weixin.qq.com/document/path/90968)）。

【推断】这些是“微信/企业微信平台到开发者服务器”的消息保护，不是“手机用户到本地 Agent”的端到端加密。平台需要接收、解密、路由和进行内容安全/合规处理，因此不能把微信/企业微信消息视为只有通信双方可读。

【建议】因此：

- 不通过微信/企业微信发送 API Key、SSH Key、设备私钥、access_token、数据库密码、完整私有源码、客户数据、未脱敏日志；
- 不给微信消息附带可执行命令或敏感参数；
- 只发送任务 ID、脱敏状态、一次性工作台链接；
- 真正敏感的内容留在工作台 E2EE 通道内，并做二次脱敏；
- 如果合规要求严格，完全关闭微信/企业微信适配，只保留自有工作台。

### 7.4 应用层 E2EE 的目标

【建议】推荐使用经过审计的标准组合，而不是自创密码学：

- 密钥协商：HPKE（[RFC 9180](https://www.rfc-editor.org/rfc/rfc9180)）或成熟的 libsodium sealed box；
- 签名：P-256 ECDSA（WebCrypto 广泛支持）或 Ed25519（需确认目标浏览器/平台支持）；
- 对称加密：AES-256-GCM；
- 密钥派生：HKDF；
- 手机私钥不可导出，桌面端密钥由 OS 安全存储保护；
- 中继只看到密文和最少路由元数据。

【事实】W3C WebCrypto 提供浏览器内密码学原语；WebAuthn 提供公钥认证（[WebCrypto](https://www.w3.org/TR/WebCryptoAPI/)、[WebAuthn](https://www.w3.org/TR/webauthn-3/)）。

【未核实】具体加密组合、密钥生命周期、迁移与恢复方案需单独做密码学设计评审和安全测试；本报告不替代实现级安全评审。

---

## 8. 推荐 MVP

### 8.1 MVP 范围（必须）

1. 本地出站连接器：mTLS WSS 到受控中继；本地不开放公网端口。
2. 手机工作台 H5/PWA：扫码/一次性链接进入；passkey 或一次性邮件登录；设备密钥绑定。
3. 只读进度：任务状态、阶段、百分比、脱敏摘要；不展示完整源码/日志。
4. 完成/待审批通知：应用内通知 + 邮件；可选 Web Push；通知只含任务 ID、脱敏摘要、工作台链接。
5. 审批：查看待审批动作、同意/拒绝；审批绑定动作哈希、单次使用、5 分钟过期。
6. 继续/停止：停止始终可用、最高优先级；继续仅限本地允许的暂停场景。
7. 危险操作本地审批：远程无法批准高风险动作；远程尝试会拒绝并审计。
8. 撤销：撤销单设备/全部设备；撤销后旧会话和旧命令立即拒绝。
9. 审计：本地 + 中继双份最小审计；哈希链或签名防篡改。
10. 配对安全：5 分钟 TTL、单次使用、SAS 核对、失败限流；二维码不含密钥/源码。

### 8.2 后续有限扩展

- `answer.select` 对本地提出的问题进行选择；
- “追加一条自然语言指令”到本地待办，由本地解析、权限引擎审查，仍不直接执行 shell；
- 可选的账号/多设备管理；
- 可选的认证服务号通知适配器（只发脱敏通知）；
- 可选的企业微信自建应用/智能机器人适配器（团队场景）；
- 独立移动端应用（如果 PWA 通知/体验不足）。

### 8.3 明确不做

- 不把公众号作为唯一登录/控制/通知通道；
- 不从手机发送任意 shell 命令；
- 不暴露本地 HTTP/Agent 端口到公网；
- 不通过微信/企业微信传密钥、源码或完整日志；
- 不做“扫码即自动绑定”；
- 不做中继可见明文的“伪 E2EE”；
- 不用永久二维码绑定所有设备；
- 不在 MVP 做多租户/团队权限/复杂组织架构。

### 8.4 验收条件

- [ ] 本地端口扫描无新增公网监听；仅出站 443。
- [ ] 绑定 token 第二次使用、过期使用、错误 SAS 均失败。
- [ ] 未签名/签名错误/过期/重放的命令被拒绝并审计。
- [ ] 高风险操作无法通过手机批准；只能本地确认或被拒绝。
- [ ] 撤销设备后，旧会话语义立即失效；中继重放旧 token 失败。
- [ ] 本地离线时中继命令不会在恢复后盲目执行；过期即丢弃。
- [ ] 通知内容不含 API Key、源码、完整路径、令牌、客户数据。
- [ ] 任一审批/执行/撤销均可从本地审计和中继审计对上。
- [ ] 手机丢失场景有明确撤销路径和演练结果。
- [ ] 中继不存明文命令/进度；TLS 终止方也不应看到业务明文（E2EE 验收）。

---

## 9. 没有认证服务号时的降级方案

【建议】默认方案不依赖任何公众号：

1. **入口**：桌面显示普通 HTTPS 二维码/一次性链接；手机用系统相机或微信“扫一扫”打开。二维码由 Nova 生成，不调用微信参数二维码接口。
2. **身份**：passkey（首推）或一次性邮件 magic link；设备密钥绑定；不要求微信号。
3. **通知**：应用内通知 + 邮件；目标手机支持时用 Web Push。微信内置浏览器不作为推送前提，提供“在系统浏览器打开”。
4. **审批/控制**：工作台内完成；高风险仍需本地确认。
5. **审计/撤销**：本地与中继双份；设备级撤销。

【推断】如果用户只有个人订阅号：

- 不能生成公众号参数二维码，不能做网页授权；
- 不能在 48 小时客服窗口之外主动发消息；
- 不能使用模板消息/订阅通知；
- 仅能配置服务器回调、接收消息和被动回复；
- 因而不能安全地完成“扫码绑定 + 主动通知 + 远程审批”的完整闭环。

【建议】个人订阅号最多作为“微信内打开工作台”的普通链接入口；不要为它申请/配置公众号密钥，不要把它纳入控制面。

【未核实】邮件、Telegram、短信等替代通道的隐私、可用性和合规性不在本次官方微信调研范围内；若引入，需单独核实其平台能力和数据保护条款。本报告不展开。

---

## 10. 仍待核实与需要用户准备的条件

### 10.1 官方文档仍待核实/存在冲突

1. **公众号回调数据格式**：一处写仅支持 XML，一处写支持 XML 和 JSON，加密文档又给 JSON 示例；必须用目标账号实测（见 2.3）。
2. **个人订阅号的消息回调/被动回复具体权限**：官方文档提供能力页，但缺少该页的账号适用表；应看公众号后台“接口权限”或官方工单确认。
3. **认证公众号（原订阅号）的主动接口**：客服/订阅通知接口表有“公众号仅认证”的表述，但产品介绍主要写认证服务号；两者不完全一致。
4. **公众号回调 URL 是否强制 ICP**：回调文档只写 URL/端口；网页授权/JS 安全域名明确 ICP。独立回调域名是否必须备案，需按后台/接入商确认。
5. **企业微信群机器人是否支持入站**：正式消息推送文档没有入站配置；官方社区答复称不支持。若要做双向，需企业微信后台/支持书面确认。
6. **Web Push 在目标手机/微信内置浏览器上的可用性**：标准存在，但平台实现和权限策略需实测。
7. **网站应用授权回调域名、企业微信独立回调 URL 的 ICP**：网站应用回调域文档没有像“业务域名”那样明确写 ICP；企业微信“回调配置”页只写 URL 公开可访问，ICP 的明确要求出现在可信域名文档中。若二者使用独立于已备案域的域名，需按平台后台和接入商确认。
8. **中国大陆公网中继的 ICP/备案要求**：平台文档之外还需看主机所在地和接入商；本报告不作法律结论。

### 10.2 需要用户准备

- **核心路径（不依赖微信）**：一个可用的中继域名 + TLS 证书 + 主机（自有 VPS 或受信云）；手机；邮箱；明确的审计保留策略。
- **若要走认证服务号可选适配**：可完成认证的服务号主体、300 元/次认证预算（部分组织可免）、HTTPS+ICP 域名、公网回调 URL、启用 API IP 白名单时的稳定出口 IP、类目/模板/订阅通知审核。
- **若要走企业微信可选适配**：企业微信管理员权限、自建应用、成员可见范围、可信公网 IP、公网回调 URL、可信域名（ICP + 归属校验）。
- **安全决策**：哪些动作允许手机审批；哪些必须本地确认；通知保留哪些任务标题；是否允许自然语言后续指令；是否允许邮件通知。
- **实现决策**：本地密钥存储方案、手机 passkey/邮件登录、E2EE 库（HPKE/libsodium）选型、审计存储与保留期、设备撤销恢复流程。
- **测试条件**：至少一台目标 Android/iPhone、微信内置浏览器与系统浏览器、弱网/断网、设备丢失/撤销演练。

---

## 附录 A：关键额度与限制速查

| 项目 | 官方限制 | 性质 |
|---|---|---|
| 公众号参数二维码 | 仅认证服务号；临时最长 30 天；永久最多 10 万个 | 【事实】 |
| 公众号网页授权 | 仅认证服务号（特殊政府/媒体公众号例外）；授权域名最多 2 个，HTTPS+ICP | 【事实】 |
| 网页授权 code | 单次使用，5 分钟过期 | 【事实】 |
| 网页授权 access_token | 7,200 秒；refresh_token 30 天 | 【事实】 |
| 公众号被动回复 | 5 秒超时，重试 3 次；超时应回复 success/空串 | 【事实】 |
| 客服消息 | 用户发消息后 5 条/48 小时；菜单/关注/扫码 3 条/1 分钟；仅认证企业主体 | 【事实】 |
| 模板消息 | 仅认证服务号；最多 5 个类目、25 个模板；日上限 10 万次起 | 【事实】 |
| 订阅通知 | 用户主动订阅；一次性一条不限时；长期仅公共服务领域；仅企业认证账号 | 【事实】接口适用范围表；【未核实】产品介绍页表述差异 |
| 公众号 access_token | 7,200 秒；服务端保存；IP 白名单外返回 40164 | 【事实】 |
| 公众号回调 URL | HTTP/HTTPS，80/443；平台主动 POST | 【事实】 |
| 企业微信 access_token | 正常 7,200 秒；应用独立；需缓存；不能给前端 | 【事实】 |
| 企业微信自建应用消息 | 每应用账号上限×200 人次/天；同一成员 30 次/分钟、1000 次/小时 | 【事实】 |
| 企业微信自建应用回调 | GET 验证 1 秒内明文；POST 5 秒超时，重试 3 次 | 【事实】 |
| 企业微信可信 IP | 新应用必须配置；仅公网 IPv4；最多 120 个；不支持 IP 段/通配 | 【事实】 |
| 企业微信消息推送/群机器人 | 20 条/分钟；文本 2048 字节；Markdown 4096 字节 | 【事实】出站限制；【未核实】是否支持入站 |
| 企业微信可信域名 | 必须有 ICP 备案并验证归属 | 【事实】 |

---

## 附录 B：官方来源清单

### 微信公众平台 / 微信开放平台

- 微信认证后有哪些特权（腾讯客服官方帮助）  
  https://kf.qq.com/faq/1612197nEJNR161219BB7Jne.html
- 微信网页授权  
  https://developers.weixin.qq.com/doc/service/guide/h5/auth.html
- 生成带参数的二维码  
  https://developers.weixin.qq.com/doc/service/api/qrcode/qrcodes/api_createqrcode
- 接收普通消息（服务号）  
  https://developers.weixin.qq.com/doc/service/guide/product/message/Receiving_standard_messages
- 接收普通消息（公众号/原订阅号）  
  https://developers.weixin.qq.com/doc/subscription/guide/product/message/Receiving_standard_messages.html
- 接收事件推送（服务号）  
  https://developers.weixin.qq.com/doc/service/guide/product/message/Receiving_event_pushes.html
- 接收事件推送（公众号/原订阅号）  
  https://developers.weixin.qq.com/doc/subscription/guide/product/message/Receiving_event_pushes.html
- 被动回复用户消息（服务号）  
  https://developers.weixin.qq.com/doc/service/guide/product/message/Passive_user_reply_message.html
- 被动回复用户消息（公众号/原订阅号）  
  https://developers.weixin.qq.com/doc/subscription/guide/product/message/Passive_user_reply_message.html
- 消息与事件推送介绍  
  https://developers.weixin.qq.com/doc/service/guide/dev/push/
- 消息加解密说明  
  https://developers.weixin.qq.com/doc/service/guide/dev/push/encryption.html
- 发送客服消息  
  https://developers.weixin.qq.com/doc/service/api/customer/message/api_sendcustommessage.html
- 客服消息介绍  
  https://developers.weixin.qq.com/doc/service/guide/product/kf/intro.html
- 模板消息  
  https://developers.weixin.qq.com/doc/service/guide/product/template_message/Template_Message_Interface.html
- 订阅通知介绍  
  https://developers.weixin.qq.com/doc/service/guide/product/subscription_messages/intro.html
- 发送订阅通知  
  https://developers.weixin.qq.com/doc/service/api/notify/notify/api_sendnewsubscribemsg
- 订阅通知的事件推送  
  https://developers.weixin.qq.com/doc/service/guide/product/subscription_messages/push.html
- 获取接口调用凭据  
  https://developers.weixin.qq.com/doc/service/api/base/api_getaccesstoken.html
- API IP 白名单  
  https://developers.weixin.qq.com/doc/oplatform/developers/basic_func/ip_whitelist.html
- 获取微信推送服务器 IP  
  https://developers.weixin.qq.com/doc/service/api/base/api_getcallbackip.html
- 域名管理  
  https://developers.weixin.qq.com/doc/oplatform/developers/basic_func/domain.html
- 公众号与服务号（平台功能介绍）  
  https://developers.weixin.qq.com/doc/oplatform/developers/product/subscription_service/
- 网站应用（平台功能介绍）  
  https://developers.weixin.qq.com/doc/oplatform/developers/product/webapp/
- 网站应用微信登录开发指南  
  https://developers.weixin.qq.com/doc/oplatform/Website_App/WeChat_Login/Wechat_Login.html
- UnionID 机制说明  
  https://developers.weixin.qq.com/doc/subscription/guide/product/unionid.html

### 企业微信

- 获取 access_token  
  https://developer.work.weixin.qq.com/document/path/91039
- 回调配置  
  https://developer.work.weixin.qq.com/document/path/90930
- 消息格式  
  https://developer.work.weixin.qq.com/document/path/90239
- 发送应用消息  
  https://developer.work.weixin.qq.com/document/path/90236
- 消息推送配置说明（原群机器人）  
  https://developer.work.weixin.qq.com/document/path/91770
- 智能机器人概述  
  https://developer.work.weixin.qq.com/document/path/101039
- 构造网页授权链接  
  https://developer.work.weixin.qq.com/document/path/91022
- 加解密方案说明  
  https://developer.work.weixin.qq.com/document/path/90968
- 可信 IP 说明  
  https://open.work.weixin.qq.com/help2/pc/21711
- 如何创建/设置自建应用权限  
  https://open.work.weixin.qq.com/help2/pc/16892
- 企业自建应用  
  https://open.work.weixin.qq.com/wwopen/manual/detail?t=selfBuildApp
- 开始使用（JS-SDK 可信域名/ICP）  
  https://developer.work.weixin.qq.com/document/path/98416
- 获取企业微信接口 IP 段  
  https://developer.work.weixin.qq.com/document/path/92520
- 获取企业微信回调 IP 段  
  https://developer.work.weixin.qq.com/document/path/92521
- 官方社区：群机器人接收消息问题（支持性答复）  
  https://developer.work.weixin.qq.com/community/question/detail?content_id=16664416507037376612

### 通用 Web / 密码学标准

- WebSocket Protocol（RFC 6455）  
  https://www.rfc-editor.org/rfc/rfc6455
- Server-Sent Events（WHATWG HTML）  
  https://html.spec.whatwg.org/multipage/server-sent-events.html
- TLS 1.3（RFC 8446）  
  https://www.rfc-editor.org/rfc/rfc8446
- OAuth 2.0 Security Best Current Practice（RFC 9700）  
  https://www.rfc-editor.org/rfc/rfc9700
- Hybrid Public Key Encryption（HPKE, RFC 9180）  
  https://www.rfc-editor.org/rfc/rfc9180
- Web Push Protocol（RFC 8030）  
  https://www.rfc-editor.org/rfc/rfc8030
- Web Push Message Encryption（RFC 8291）  
  https://www.rfc-editor.org/rfc/rfc8291
- WebAuthn Level 3（W3C）  
  https://www.w3.org/TR/webauthn-3/
- Web Cryptography API（W3C）  
  https://www.w3.org/TR/WebCryptoAPI/
- Cloudflare Tunnel 官方文档  
  https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/

---

## 附录 C：一句话判断

【建议】Nova 应做“手机工作台 + 一次性扫码/链接绑定 + 本地出站受控中继 + 设备密钥 + E2EE + 本地审批”，微信只做可选入口和可选通知；在没有认证服务号时，主路径仍然成立。公众号不是主路径，企业微信只适合作为企业团队的可选通道。
