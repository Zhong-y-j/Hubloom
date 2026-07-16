import type { A2uiMessage, Scenario } from "@/types/a2ui";

/**
 * 与官方 @a2ui/lit basicCatalog.id 对齐。
 * MessageProcessor 处理时也会用运行时 catalog.id 覆盖。
 */
export const BASIC_CATALOG_ID =
  "https://a2ui.org/specification/v0_9/catalogs/basic/catalog.json";

function msg(payload: Omit<A2uiMessage, "version">): A2uiMessage {
  return { version: "v0.9.1", ...payload } as A2uiMessage;
}

/**
 * Basic Catalog 全组件图鉴（共 18 个）：
 * Text / TextField / Button / Card / Column / Row / List /
 * CheckBox / ChoicePicker / DateTimeInput / Slider / Tabs /
 * Modal / Divider / Image / Icon / Video / AudioPlayer
 *
 * 样式请改 src/styles.css 的 --a2ui-*，Agent JSON 不负责外观。
 */
const catalogGallery: A2uiMessage[] = [
  msg({
    createSurface: { surfaceId: "gallery", catalogId: BASIC_CATALOG_ID },
  }),
  msg({
    updateComponents: {
      surfaceId: "gallery",
      components: [
        {
          id: "root",
          component: "Column",
          children: [
            "page-title",
            "page-lead",
            "sec-text",
            "sec-icon",
            "sec-divider",
            "sec-media",
            "sec-inputs",
            "sec-choice",
            "sec-datetime",
            "sec-slider",
            "sec-buttons",
            "sec-list",
            "sec-tabs",
            "sec-modal",
          ],
          align: "stretch",
        },

        {
          id: "page-title",
          component: "Text",
          text: "A2UI Basic Catalog 组件图鉴",
          variant: "h2",
        },
        {
          id: "page-lead",
          component: "Text",
          text: "下列卡片覆盖 Catalog 全部组件。改 styles.css 里的 --a2ui-* 即可调样式。",
          variant: "body",
        },

        // ——— Text ———
        { id: "sec-text", component: "Card", child: "sec-text-body" },
        {
          id: "sec-text-body",
          component: "Column",
          children: [
            "sec-text-h",
            "text-h1",
            "text-h2",
            "text-h3",
            "text-h4",
            "text-h5",
            "text-body",
            "text-caption",
          ],
        },
        {
          id: "sec-text-h",
          component: "Text",
          text: "Text · variant",
          variant: "h4",
        },
        { id: "text-h1", component: "Text", text: "h1 标题", variant: "h1" },
        { id: "text-h2", component: "Text", text: "h2 标题", variant: "h2" },
        { id: "text-h3", component: "Text", text: "h3 标题", variant: "h3" },
        { id: "text-h4", component: "Text", text: "h4 标题", variant: "h4" },
        { id: "text-h5", component: "Text", text: "h5 标题", variant: "h5" },
        {
          id: "text-body",
          component: "Text",
          text: "body 正文：用于说明与摘要。",
          variant: "body",
        },
        {
          id: "text-caption",
          component: "Text",
          text: "caption 辅助说明",
          variant: "caption",
        },

        // ——— Icon ———
        { id: "sec-icon", component: "Card", child: "sec-icon-body" },
        {
          id: "sec-icon-body",
          component: "Column",
          children: ["sec-icon-h", "icon-row"],
        },
        {
          id: "sec-icon-h",
          component: "Text",
          text: "Icon · Material Symbols 名",
          variant: "h4",
        },
        {
          id: "icon-row",
          component: "Row",
          children: [
            "icon-home",
            "icon-star",
            "icon-settings",
            "icon-favorite",
            "icon-notifications",
            "icon-search",
          ],
          align: "center",
        },
        { id: "icon-home", component: "Icon", name: "home" },
        { id: "icon-star", component: "Icon", name: "star" },
        { id: "icon-settings", component: "Icon", name: "settings" },
        { id: "icon-favorite", component: "Icon", name: "favorite" },
        {
          id: "icon-notifications",
          component: "Icon",
          name: "notifications",
        },
        { id: "icon-search", component: "Icon", name: "search" },

        // ——— Divider ———
        { id: "sec-divider", component: "Card", child: "sec-divider-body" },
        {
          id: "sec-divider-body",
          component: "Column",
          children: [
            "sec-divider-h",
            "divider-before",
            "divider-h",
            "divider-after",
          ],
        },
        {
          id: "sec-divider-h",
          component: "Text",
          text: "Divider",
          variant: "h4",
        },
        {
          id: "divider-before",
          component: "Text",
          text: "分割线上方",
          variant: "caption",
        },
        { id: "divider-h", component: "Divider", axis: "horizontal" },
        {
          id: "divider-after",
          component: "Text",
          text: "分割线下方",
          variant: "caption",
        },

        // ——— Image / Video / AudioPlayer ———
        { id: "sec-media", component: "Card", child: "sec-media-body" },
        {
          id: "sec-media-body",
          component: "Column",
          children: [
            "sec-media-h",
            "media-image-label",
            "media-image",
            "media-video-label",
            "media-video",
            "media-audio-label",
            "media-audio",
          ],
        },
        {
          id: "sec-media-h",
          component: "Text",
          text: "Image / Video / AudioPlayer",
          variant: "h4",
        },
        {
          id: "media-image-label",
          component: "Text",
          text: "Image",
          variant: "caption",
        },
        {
          id: "media-image",
          component: "Image",
          url: { path: "/media/imageUrl" },
          description: "示例图片",
          fit: "cover",
          variant: "mediumFeature",
        },
        {
          id: "media-video-label",
          component: "Text",
          text: "Video",
          variant: "caption",
        },
        {
          id: "media-video",
          component: "Video",
          url: { path: "/media/videoUrl" },
        },
        {
          id: "media-audio-label",
          component: "Text",
          text: "AudioPlayer",
          variant: "caption",
        },
        {
          id: "media-audio",
          component: "AudioPlayer",
          url: { path: "/media/audioUrl" },
          description: { path: "/media/audioTitle" },
        },

        // ——— TextField ———
        { id: "sec-inputs", component: "Card", child: "sec-inputs-body" },
        {
          id: "sec-inputs-body",
          component: "Column",
          children: [
            "sec-inputs-h",
            "field-short",
            "field-long",
            "field-number",
            "field-obscured",
            "field-check",
          ],
        },
        {
          id: "sec-inputs-h",
          component: "Text",
          text: "TextField / CheckBox",
          variant: "h4",
        },
        {
          id: "field-short",
          component: "TextField",
          label: "短文本 shortText",
          value: { path: "/form/shortText" },
          variant: "shortText",
        },
        {
          id: "field-long",
          component: "TextField",
          label: "长文本 longText",
          value: { path: "/form/longText" },
          variant: "longText",
        },
        {
          id: "field-number",
          component: "TextField",
          label: "数字 number",
          value: { path: "/form/number" },
          variant: "number",
        },
        {
          id: "field-obscured",
          component: "TextField",
          label: "密码 obscured",
          value: { path: "/form/password" },
          variant: "obscured",
        },
        {
          id: "field-check",
          component: "CheckBox",
          label: "我已阅读并同意",
          value: { path: "/form/agreed" },
        },

        // ——— ChoicePicker ———
        { id: "sec-choice", component: "Card", child: "sec-choice-body" },
        {
          id: "sec-choice-body",
          component: "Column",
          children: [
            "sec-choice-h",
            "choice-exclusive-label",
            "choice-exclusive",
            "choice-multi-label",
            "choice-multi",
          ],
        },
        {
          id: "sec-choice-h",
          component: "Text",
          text: "ChoicePicker",
          variant: "h4",
        },
        {
          id: "choice-exclusive-label",
          component: "Text",
          text: "单选 · chips",
          variant: "caption",
        },
        {
          id: "choice-exclusive",
          component: "ChoicePicker",
          label: "套餐",
          options: [
            { label: "基础", value: "basic" },
            { label: "专业", value: "pro" },
            { label: "企业", value: "enterprise" },
          ],
          value: { path: "/form/plan" },
          variant: "mutuallyExclusive",
          displayStyle: "chips",
        },
        {
          id: "choice-multi-label",
          component: "Text",
          text: "多选 · checkbox",
          variant: "caption",
        },
        {
          id: "choice-multi",
          component: "ChoicePicker",
          label: "附加服务",
          options: [
            { label: "内饰清洁", value: "interior" },
            { label: "打蜡", value: "wax" },
            { label: "轮胎保养", value: "tires" },
          ],
          value: { path: "/form/extras" },
          variant: "multipleSelection",
          displayStyle: "checkbox",
        },

        // ——— DateTimeInput ———
        { id: "sec-datetime", component: "Card", child: "sec-datetime-body" },
        {
          id: "sec-datetime-body",
          component: "Column",
          children: ["sec-datetime-h", "dt-date", "dt-time", "dt-both"],
        },
        {
          id: "sec-datetime-h",
          component: "Text",
          text: "DateTimeInput",
          variant: "h4",
        },
        {
          id: "dt-date",
          component: "DateTimeInput",
          label: "仅日期",
          value: { path: "/form/dateOnly" },
          enableDate: true,
          enableTime: false,
        },
        {
          id: "dt-time",
          component: "DateTimeInput",
          label: "仅时间",
          value: { path: "/form/timeOnly" },
          enableDate: false,
          enableTime: true,
        },
        {
          id: "dt-both",
          component: "DateTimeInput",
          label: "日期 + 时间",
          value: { path: "/form/dateTime" },
          enableDate: true,
          enableTime: true,
        },

        // ——— Slider ———
        { id: "sec-slider", component: "Card", child: "sec-slider-body" },
        {
          id: "sec-slider-body",
          component: "Column",
          children: ["sec-slider-h", "slider-demo", "slider-value-text"],
        },
        {
          id: "sec-slider-h",
          component: "Text",
          text: "Slider",
          variant: "h4",
        },
        {
          id: "slider-demo",
          component: "Slider",
          label: "进度 / 音量",
          value: { path: "/form/progress" },
          min: 0,
          max: 100,
        },
        {
          id: "slider-value-text",
          component: "Text",
          text: { path: "/form/progressLabel" },
          variant: "caption",
        },

        // ——— Button + Row ———
        { id: "sec-buttons", component: "Card", child: "sec-buttons-body" },
        {
          id: "sec-buttons-body",
          component: "Column",
          children: ["sec-buttons-h", "btn-row"],
        },
        {
          id: "sec-buttons-h",
          component: "Text",
          text: "Button · Row 布局",
          variant: "h4",
        },
        {
          id: "btn-row",
          component: "Row",
          children: ["btn-primary", "btn-default", "btn-borderless"],
          align: "center",
        },
        { id: "btn-primary-label", component: "Text", text: "primary" },
        {
          id: "btn-primary",
          component: "Button",
          child: "btn-primary-label",
          variant: "primary",
          action: { event: { name: "gallery_primary" } },
        },
        { id: "btn-default-label", component: "Text", text: "default" },
        {
          id: "btn-default",
          component: "Button",
          child: "btn-default-label",
          variant: "default",
          action: { event: { name: "gallery_default" } },
        },
        { id: "btn-borderless-label", component: "Text", text: "borderless" },
        {
          id: "btn-borderless",
          component: "Button",
          child: "btn-borderless-label",
          variant: "borderless",
          action: { event: { name: "gallery_borderless" } },
        },

        // ——— List（模板展开） ———
        { id: "sec-list", component: "Card", child: "sec-list-body" },
        {
          id: "sec-list-body",
          component: "Column",
          children: ["sec-list-h", "item-list"],
        },
        {
          id: "sec-list-h",
          component: "Text",
          text: "List · 数据模板",
          variant: "h4",
        },
        {
          id: "item-list",
          component: "List",
          children: { componentId: "list-row", path: "/items" },
          direction: "vertical",
        },
        {
          id: "list-row",
          component: "Row",
          children: ["list-name", "list-qty"],
          justify: "spaceBetween",
          align: "center",
        },
        {
          id: "list-name",
          component: "Text",
          text: { path: "name" },
          variant: "body",
        },
        {
          id: "list-qty",
          component: "Text",
          text: { path: "qty" },
          variant: "caption",
        },

        // ——— Tabs ———
        { id: "sec-tabs", component: "Card", child: "sec-tabs-body" },
        {
          id: "sec-tabs-body",
          component: "Column",
          children: ["sec-tabs-h", "tabs-demo"],
        },
        {
          id: "sec-tabs-h",
          component: "Text",
          text: "Tabs",
          variant: "h4",
        },
        {
          id: "tabs-demo",
          component: "Tabs",
          tabs: [
            { title: "概览", child: "tab-overview" },
            { title: "详情", child: "tab-detail" },
            { title: "备注", child: "tab-note" },
          ],
        },
        {
          id: "tab-overview",
          component: "Text",
          text: "这是「概览」页签内容。",
          variant: "body",
        },
        {
          id: "tab-detail",
          component: "Text",
          text: "这是「详情」页签内容。",
          variant: "body",
        },
        {
          id: "tab-note",
          component: "Text",
          text: "这是「备注」页签内容。",
          variant: "body",
        },

        // ——— Modal ———
        { id: "sec-modal", component: "Card", child: "sec-modal-body" },
        {
          id: "sec-modal-body",
          component: "Column",
          children: ["sec-modal-h", "modal-demo"],
        },
        {
          id: "sec-modal-h",
          component: "Text",
          text: "Modal · 点按钮打开",
          variant: "h4",
        },
        {
          id: "modal-demo",
          component: "Modal",
          trigger: "modal-open-btn",
          content: "modal-content",
        },
        { id: "modal-open-label", component: "Text", text: "打开 Modal" },
        {
          id: "modal-open-btn",
          component: "Button",
          child: "modal-open-label",
          variant: "primary",
          action: { event: { name: "open_modal" } },
        },
        {
          id: "modal-content",
          component: "Column",
          children: ["modal-title", "modal-body-text"],
        },
        {
          id: "modal-title",
          component: "Text",
          text: "Modal 内容",
          variant: "h3",
        },
        {
          id: "modal-body-text",
          component: "Text",
          text: "这是弹层里的内容。样式仍由客户端 --a2ui-* 控制。",
          variant: "body",
        },
      ],
    },
  }),
  msg({
    updateDataModel: {
      surfaceId: "gallery",
      path: "/",
      value: {
        media: {
          imageUrl:
            "https://images.unsplash.com/photo-1478737270239-2f02b77fc618?w=640&h=360&fit=crop",
          videoUrl: "https://www.w3schools.com/html/mov_bbb.mp4",
          audioUrl:
            "https://www.soundhelix.com/examples/mp3/SoundHelix-Song-1.mp3",
          audioTitle: "示例音频 · SoundHelix",
        },
        form: {
          shortText: "阳光花园",
          longText: "备注：请带上备用钥匙。",
          number: "2",
          password: "secret",
          agreed: true,
          plan: ["pro"],
          extras: ["interior", "wax"],
          dateOnly: "2026-07-20T00:00:00",
          timeOnly: "2026-07-20T10:30:00",
          dateTime: "2026-07-20T10:30:00",
          progress: 42,
          progressLabel: "当前值：42（可拖动 Slider）",
        },
        items: [
          { name: "内饰清洁", qty: "×1" },
          { name: "打蜡", qty: "×1" },
          { name: "轮胎保养", qty: "×2" },
        ],
      },
    },
  }),
];

/** 场景 1：缺参表单 —— Column / TextField / Button */
const bookingForm: A2uiMessage[] = [
  msg({
    createSurface: { surfaceId: "booking", catalogId: BASIC_CATALOG_ID },
  }),
  msg({
    updateComponents: {
      surfaceId: "booking",
      components: [
        {
          id: "root",
          component: "Column",
          children: ["title", "community", "plate", "date", "actions"],
        },
        {
          id: "title",
          component: "Text",
          text: "创建洗车预约",
          variant: "h2",
        },
        {
          id: "community",
          component: "TextField",
          label: "小区",
          value: { path: "/booking/community" },
        },
        {
          id: "plate",
          component: "TextField",
          label: "车牌号",
          value: { path: "/booking/plateNo" },
        },
        {
          id: "date",
          component: "DateTimeInput",
          label: "预约日期",
          value: { path: "/booking/date" },
          enableDate: true,
          enableTime: false,
        },
        {
          id: "actions",
          component: "Row",
          children: ["submit-btn", "cancel-btn"],
        },
        { id: "submit-label", component: "Text", text: "确认预约" },
        {
          id: "submit-btn",
          component: "Button",
          child: "submit-label",
          variant: "primary",
          action: { event: { name: "confirm_booking" } },
        },
        { id: "cancel-label", component: "Text", text: "取消" },
        {
          id: "cancel-btn",
          component: "Button",
          child: "cancel-label",
          action: { event: { name: "cancel_booking" } },
        },
      ],
    },
  }),
  msg({
    updateDataModel: {
      surfaceId: "booking",
      path: "/booking",
      value: {
        community: "",
        plateNo: "",
        date: "2026-07-20T10:00:00",
      },
    },
  }),
];

/** 场景 2：确认卡 —— Card / Text / Button */
const confirmCard: A2uiMessage[] = [
  msg({
    createSurface: { surfaceId: "confirm", catalogId: BASIC_CATALOG_ID },
  }),
  msg({
    updateComponents: {
      surfaceId: "confirm",
      components: [
        { id: "root", component: "Card", child: "body" },
        {
          id: "body",
          component: "Column",
          children: ["title", "summary", "actions"],
        },
        {
          id: "title",
          component: "Text",
          text: "确认取消订单？",
          variant: "h2",
        },
        {
          id: "summary",
          component: "Text",
          text: { path: "/order/summary" },
          variant: "body",
        },
        {
          id: "actions",
          component: "Row",
          children: ["yes-btn", "no-btn"],
        },
        { id: "yes-label", component: "Text", text: "确认取消" },
        {
          id: "yes-btn",
          component: "Button",
          child: "yes-label",
          variant: "primary",
          action: {
            event: {
              name: "cancel_order",
              context: { orderId: { path: "/order/id" } },
            },
          },
        },
        { id: "no-label", component: "Text", text: "返回" },
        {
          id: "no-btn",
          component: "Button",
          child: "no-label",
          action: { event: { name: "dismiss" } },
        },
      ],
    },
  }),
  msg({
    updateDataModel: {
      surfaceId: "confirm",
      path: "/order",
      value: {
        id: "ORD-20260716-001",
        summary: "订单 ORD-20260716-001 · 阳光花园 · 粤B12345 · 明天 10:00",
      },
    },
  }),
];

/** 场景 3：结果列表 —— Column + 多张 Card */
const orderList: A2uiMessage[] = [
  msg({
    createSurface: { surfaceId: "orders", catalogId: BASIC_CATALOG_ID },
  }),
  msg({
    updateComponents: {
      surfaceId: "orders",
      components: [
        {
          id: "root",
          component: "Column",
          children: ["title", "item-0", "item-1"],
        },
        { id: "title", component: "Text", text: "最近预约", variant: "h2" },
        { id: "item-0", component: "Card", child: "item-0-body" },
        {
          id: "item-0-body",
          component: "Column",
          children: ["item-0-title", "item-0-desc"],
        },
        {
          id: "item-0-title",
          component: "Text",
          text: { path: "/orders/0/title" },
          variant: "h3",
        },
        {
          id: "item-0-desc",
          component: "Text",
          text: { path: "/orders/0/desc" },
        },
        { id: "item-1", component: "Card", child: "item-1-body" },
        {
          id: "item-1-body",
          component: "Column",
          children: ["item-1-title", "item-1-desc"],
        },
        {
          id: "item-1-title",
          component: "Text",
          text: { path: "/orders/1/title" },
          variant: "h3",
        },
        {
          id: "item-1-desc",
          component: "Text",
          text: { path: "/orders/1/desc" },
        },
      ],
    },
  }),
  msg({
    updateDataModel: {
      surfaceId: "orders",
      path: "/orders",
      value: [
        {
          title: "ORD-001 · 待服务",
          desc: "阳光花园 · 粤B12345 · 明天 10:00",
        },
        {
          title: "ORD-002 · 已完成",
          desc: "翠湖苑 · 粤B88888 · 昨天 14:30",
        },
      ],
    },
  }),
];

/** 原 Markdown 文档全文（Agent 自然语言回复更贴近这种形态） */
const KEY_CABINET_MARKDOWN = `# 智能钥匙柜存取规则

## 一、柜子本身的状态流转

| 阶段 | 触发操作 | 规则说明 |
|------|----------|----------|
| 新建 | 创建柜子 | 填写柜名（如 A01）、物联网 ID、柜门数（1-128）、所在小区、是否启用等基础信息。 |
| 初始化 | 初始化接口 | 为每个柜门生成二维码与取件地址；未初始化的柜子不能启用。 |
| 启用 | 启用接口 | 只有已初始化的柜子才能启用；启用后柜门只能通过订单扫码开门。 |
| 禁用 | 禁用接口 | 只有没有关联订单的情况下才能禁用；用于测试或运维。 |

## 二、开门权限规则

| 场景 | 条件 | 允许的操作 |
|------|------|------------|
| 生产环境（取还钥匙） | 柜子已启用 + 有关联洗车订单 | 扫码/输入取件码开门 |
| 测试/运维 | 柜子已禁用 + 没有关联订单 | 管理员可开任意柜门 |
| 新柜上机测试 | 已初始化但未启用 | 可测试开门 |

## 三、实际部署情况

| 柜名 | 所在小区 | 柜门数 | 是否启用 |
|------|----------|--------|----------|
| A01 | 测试小区3 | 10 | ✓ |
| A02 | 测试小区3 | 10 | ✓ |
| B01 | 鄞新电力 | 10 | ✓ |
| M011 | 骑际马术 | 10 | ✓ |
| M022 | 骑际马术 | 10 | ✓ |

所有柜子已初始化并生成二维码。

## 四、存取全流程

\`\`\`
1. 车主到达 → 员工扫码/输入取件码 → 开柜取钥匙（OpenDoor）
2. → 执行服务（processStartTime → processFinishTime）
3. → 服务完成 → 开柜还钥匙（OpenDoor）
4. → 订单完成（completedTime），存取记录归档
\`\`\`

\`orderRemarks\` 字段存车牌和车位号，方便追溯每次存取对应哪辆车。
`;

/**
 * 场景：整篇 Markdown 塞进一个 Text —— 更接近 Agent 文本回复。
 * A2UI 只包一层 Card/Text，内容仍是 Markdown。
 */
const keyCabinetMarkdown: A2uiMessage[] = [
  msg({
    createSurface: { surfaceId: "key-md", catalogId: BASIC_CATALOG_ID },
  }),
  msg({
    updateComponents: {
      surfaceId: "key-md",
      components: [
        { id: "root", component: "Card", child: "body" },
        {
          id: "body",
          component: "Column",
          children: ["md-doc"],
          align: "stretch",
        },
        {
          id: "md-doc",
          component: "Text",
          text: { path: "/markdown" },
        },
      ],
    },
  }),
  msg({
    updateDataModel: {
      surfaceId: "key-md",
      path: "/",
      value: { markdown: KEY_CABINET_MARKDOWN },
    },
  }),
];

/**
 * 场景：Markdown 文档 → 结构化 A2UI JSON
 * 对应「智能钥匙柜存取规则」：标题 / 小节 Card / List 表格行 / 流程说明
 */
const keyCabinetRules: A2uiMessage[] = [
  msg({
    createSurface: { surfaceId: "key-rules", catalogId: BASIC_CATALOG_ID },
  }),
  msg({
    updateComponents: {
      surfaceId: "key-rules",
      components: [
        {
          id: "root",
          component: "Column",
          children: [
            "doc-title",
            "sec-status",
            "sec-permission",
            "sec-deploy",
            "sec-flow",
          ],
          align: "stretch",
        },
        {
          id: "doc-title",
          component: "Text",
          text: "智能钥匙柜存取规则",
          variant: "h2",
        },

        // —— 一、柜子状态流转 ——
        { id: "sec-status", component: "Card", child: "sec-status-body" },
        {
          id: "sec-status-body",
          component: "Column",
          children: ["sec-status-h", "status-header", "status-list"],
          align: "stretch",
        },
        {
          id: "sec-status-h",
          component: "Text",
          text: "一、柜子本身的状态流转",
          variant: "h3",
        },
        {
          id: "status-header",
          component: "Row",
          children: ["status-h-stage", "status-h-trigger", "status-h-rule"],
          justify: "spaceBetween",
        },
        {
          id: "status-h-stage",
          component: "Text",
          text: "阶段",
          variant: "caption",
        },
        {
          id: "status-h-trigger",
          component: "Text",
          text: "触发操作",
          variant: "caption",
        },
        {
          id: "status-h-rule",
          component: "Text",
          text: "规则说明",
          variant: "caption",
        },
        {
          id: "status-list",
          component: "List",
          children: { componentId: "status-row", path: "/statusRows" },
        },
        {
          id: "status-row",
          component: "Column",
          children: ["status-divider", "status-data-row"],
        },
        { id: "status-divider", component: "Divider" },
        {
          id: "status-data-row",
          component: "Row",
          children: ["status-stage", "status-trigger", "status-rule"],
          align: "start",
        },
        {
          id: "status-stage",
          component: "Text",
          text: { path: "stage" },
          variant: "body",
        },
        {
          id: "status-trigger",
          component: "Text",
          text: { path: "trigger" },
          variant: "body",
        },
        {
          id: "status-rule",
          component: "Text",
          text: { path: "rule" },
          variant: "caption",
        },

        // —— 二、开门权限 ——
        { id: "sec-permission", component: "Card", child: "sec-permission-body" },
        {
          id: "sec-permission-body",
          component: "Column",
          children: ["sec-permission-h", "permission-header", "permission-list"],
          align: "stretch",
        },
        {
          id: "sec-permission-h",
          component: "Text",
          text: "二、开门权限规则",
          variant: "h3",
        },
        {
          id: "permission-header",
          component: "Row",
          children: [
            "permission-h-scene",
            "permission-h-condition",
            "permission-h-action",
          ],
          justify: "spaceBetween",
        },
        {
          id: "permission-h-scene",
          component: "Text",
          text: "场景",
          variant: "caption",
        },
        {
          id: "permission-h-condition",
          component: "Text",
          text: "条件",
          variant: "caption",
        },
        {
          id: "permission-h-action",
          component: "Text",
          text: "允许的操作",
          variant: "caption",
        },
        {
          id: "permission-list",
          component: "List",
          children: { componentId: "permission-row", path: "/permissionRows" },
        },
        {
          id: "permission-row",
          component: "Column",
          children: ["permission-divider", "permission-data-row"],
        },
        { id: "permission-divider", component: "Divider" },
        {
          id: "permission-data-row",
          component: "Row",
          children: [
            "permission-scene",
            "permission-condition",
            "permission-action",
          ],
          align: "start",
        },
        {
          id: "permission-scene",
          component: "Text",
          text: { path: "scene" },
          variant: "body",
        },
        {
          id: "permission-condition",
          component: "Text",
          text: { path: "condition" },
          variant: "caption",
        },
        {
          id: "permission-action",
          component: "Text",
          text: { path: "action" },
          variant: "body",
        },

        // —— 三、实际部署 ——
        { id: "sec-deploy", component: "Card", child: "sec-deploy-body" },
        {
          id: "sec-deploy-body",
          component: "Column",
          children: [
            "sec-deploy-h",
            "deploy-header",
            "deploy-list",
            "deploy-note",
          ],
          align: "stretch",
        },
        {
          id: "sec-deploy-h",
          component: "Text",
          text: "三、实际部署情况",
          variant: "h3",
        },
        {
          id: "deploy-header",
          component: "Row",
          children: [
            "deploy-h-name",
            "deploy-h-community",
            "deploy-h-doors",
            "deploy-h-enabled",
          ],
          justify: "spaceBetween",
        },
        {
          id: "deploy-h-name",
          component: "Text",
          text: "柜名",
          variant: "caption",
        },
        {
          id: "deploy-h-community",
          component: "Text",
          text: "所在小区",
          variant: "caption",
        },
        {
          id: "deploy-h-doors",
          component: "Text",
          text: "柜门数",
          variant: "caption",
        },
        {
          id: "deploy-h-enabled",
          component: "Text",
          text: "是否启用",
          variant: "caption",
        },
        {
          id: "deploy-list",
          component: "List",
          children: { componentId: "deploy-row", path: "/deploymentRows" },
        },
        {
          id: "deploy-row",
          component: "Column",
          children: ["deploy-divider", "deploy-data-row"],
        },
        { id: "deploy-divider", component: "Divider" },
        {
          id: "deploy-data-row",
          component: "Row",
          children: [
            "deploy-name",
            "deploy-community",
            "deploy-doors",
            "deploy-enabled-icon",
          ],
          justify: "spaceBetween",
          align: "center",
        },
        {
          id: "deploy-name",
          component: "Text",
          text: { path: "name" },
          variant: "body",
        },
        {
          id: "deploy-community",
          component: "Text",
          text: { path: "community" },
          variant: "caption",
        },
        {
          id: "deploy-doors",
          component: "Text",
          text: { path: "doors" },
          variant: "body",
        },
        {
          id: "deploy-enabled-icon",
          component: "Icon",
          name: "check",
        },

        {
          id: "deploy-note",
          component: "Text",
          text: { path: "/deployNote" },
          variant: "caption",
        },

        // —— 四、存取全流程 ——
        { id: "sec-flow", component: "Card", child: "sec-flow-body" },
        {
          id: "sec-flow-body",
          component: "Column",
          children: ["sec-flow-h", "flow-md", "flow-note"],
        },
        {
          id: "sec-flow-h",
          component: "Text",
          text: "四、存取全流程",
          variant: "h3",
        },
        {
          id: "flow-md",
          component: "Text",
          text: { path: "/flowMarkdown" },
        },
        {
          id: "flow-note",
          component: "Text",
          text: { path: "/flowNote" },
          variant: "caption",
        },
      ],
    },
  }),
  msg({
    updateDataModel: {
      surfaceId: "key-rules",
      path: "/",
      value: {
        statusRows: [
          {
            stage: "新建",
            trigger: "创建柜子",
            rule: "填写柜名（如 A01）、物联网 ID、柜门数（1-128）、所在小区、是否启用等基础信息。",
          },
          {
            stage: "初始化",
            trigger: "初始化接口",
            rule: "为每个柜门生成二维码与取件地址；未初始化的柜子不能启用。",
          },
          {
            stage: "启用",
            trigger: "启用接口",
            rule: "只有已初始化的柜子才能启用；启用后柜门只能通过订单扫码开门。",
          },
          {
            stage: "禁用",
            trigger: "禁用接口",
            rule: "只有没有关联订单的情况下才能禁用；用于测试或运维。",
          },
        ],
        permissionRows: [
          {
            scene: "生产环境（取还钥匙）",
            condition: "柜子已启用 + 有关联洗车订单",
            action: "扫码/输入取件码开门",
          },
          {
            scene: "测试/运维",
            condition: "柜子已禁用 + 没有关联订单",
            action: "管理员可开任意柜门",
          },
          {
            scene: "新柜上机测试",
            condition: "已初始化但未启用",
            action: "可测试开门",
          },
        ],
        deploymentRows: [
          { name: "A01", community: "测试小区3", doors: "10" },
          { name: "A02", community: "测试小区3", doors: "10" },
          { name: "B01", community: "鄞新电力", doors: "10" },
          { name: "M011", community: "骑际马术", doors: "10" },
          { name: "M022", community: "骑际马术", doors: "10" },
        ],
        deployNote: "所有柜子已初始化并生成二维码。",
        flowMarkdown: [
          "```",
          "1. 车主到达 → 员工扫码/输入取件码 → 开柜取钥匙（OpenDoor）",
          "2. → 执行服务（processStartTime → processFinishTime）",
          "3. → 服务完成 → 开柜还钥匙（OpenDoor）",
          "4. → 订单完成（completedTime），存取记录归档",
          "```",
        ].join("\n"),
        flowNote:
          "orderRemarks 字段存车牌和车位号，方便追溯每次存取对应哪辆车。",
      },
    },
  }),
];

export const SCENARIOS: Scenario[] = [
  {
    id: "key_cabinet_markdown",
    title: "纯 Markdown",
    userSays: "智能钥匙柜的存取规则是什么？",
    agentSays: "下面用 Markdown 说明：",
    why: "推荐路径：Agent 输出 Markdown 文本；客户端用现有 markdown 渲染（或包一层 A2UI Text）。长文档、表格、说明文更适合这种形态，不必强迫 Agent 吐组件 JSON。",
    messages: keyCabinetMarkdown,
  },
  {
    id: "key_cabinet_rules",
    title: "结构化 A2UI",
    userSays: "智能钥匙柜的存取规则是什么？",
    agentSays: "整理成卡片结构如下：",
    why: "对比用：同一内容拆成 Card/List/Row。表格会变丑、JSON 更长。适合交互表单/确认按钮，不适合整篇说明文档。",
    messages: keyCabinetRules,
  },
  {
    id: "catalog_gallery",
    title: "组件图鉴",
    userSays: "把 Basic Catalog 里所有组件都展示出来",
    agentSays: "好的，下面是全组件图鉴：",
    why: "覆盖 Text / Icon / Divider / Image / Video / AudioPlayer / TextField / CheckBox / ChoicePicker / DateTimeInput / Slider / Button / Row / Column / Card / List / Tabs / Modal。用 styles.css 的 --a2ui-* 调样式。",
    messages: catalogGallery,
  },
  {
    id: "booking_form",
    title: "预约表单",
    userSays: "帮我预约洗车",
    agentSays: "好的，请补充以下信息：",
    why: "Agent 发现缺参，输出 A2UI 表单（Column / TextField / Button）。",
    messages: bookingForm,
  },
  {
    id: "confirm_card",
    title: "确认卡片",
    userSays: "取消那个订单",
    agentSays: "即将取消，请确认：",
    why: "写操作前先出确认卡（Card / Text / Button）。",
    messages: confirmCard,
  },
  {
    id: "order_list",
    title: "结果列表",
    userSays: "看看我最近的预约",
    agentSays: "查到 2 条记录：",
    why: "查询结果用多张 Card 列表展示。",
    messages: orderList,
  },
];

export function getScenario(id: string): Scenario | undefined {
  return SCENARIOS.find((s) => s.id === id);
}
