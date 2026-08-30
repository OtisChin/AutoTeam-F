export const NAV_ITEMS = [
  { key: 'dashboard', group: '控制台', icon: 'dashboard', label: '仪表盘', description: '账号池概览与核心操作', mobilePrimary: true },
  { key: 'register', group: '账号', icon: 'user-plus', label: '注册账号', description: '批量注册与账号生产', mobilePrimary: true },
  { key: 'mailAccounts', group: '账号', icon: 'mail', label: '邮箱管理', description: '邮箱账号与授权状态' },
  { key: 'cardpool', group: '支付', icon: 'cards', label: '卡池', description: '支付卡资源管理', mobilePrimary: true },
  { key: 'bindcard', group: '支付', icon: 'link', label: '自动绑卡服务', description: '账号与支付卡绑定' },
  { key: 'gopay', group: '支付', icon: 'wallet', label: 'GoPay', description: 'GoPay 支付工作流' },
  { key: 'paypal', group: '支付', icon: 'wallet', label: 'PayPal', description: 'PayPal 提链与协议支付' },
  { key: 'ideal', group: '支付', icon: 'wallet', label: '荷兰 iDEAL', description: 'iDEAL 提链与支付' },
  { key: 'brazilPix', group: '支付', icon: 'wallet', label: '巴西 PIX', description: 'PIX 提链与支付' },
  { key: 'indiaUpi', group: '支付', icon: 'wallet', label: '印度 UPI', description: 'UPI 提链与支付' },
  { key: 'kakaoPay', group: '支付', icon: 'wallet', label: '韩国 Kakao', description: 'Kakao Pay 提链与支付' },
  { key: 'momoVn', group: '支付', icon: 'wallet', label: '越南 MoMo', description: 'MoMo 提链与支付' },
  { key: 'gcashPh', group: '支付', icon: 'wallet', label: '菲律宾 GCash', description: 'GCash 提链与支付' },
  { key: 'oauthPhones', group: '授权', icon: 'phone', label: 'OAuth 手机号', description: '授权手机号池' },
  { key: 'oauthPhoneRecords', group: '授权', icon: 'records', label: 'OAuth 取号记录', description: '手机号使用记录' },
  { key: 'oauth', group: '授权', icon: 'key', label: 'OAuth 登录', description: '手动授权与登录' },
  { key: 'trade', group: '商务', icon: 'commerce', label: '交易管理', description: 'CDK 交易与兑换' },
  { key: 'cpa2sub', group: '工具', icon: 'tools', label: 'CPA 转 Sub2API', description: '凭据转换工具' },
  { key: 'tasks', group: '系统', icon: 'history', label: '任务历史', description: '后台任务与执行记录', mobilePrimary: true },
  { key: 'logs', group: '系统', icon: 'logs', label: '日志', description: '运行日志与诊断信息' },
  { key: 'settings', group: '系统', icon: 'settings', label: '设置', description: '服务与自动化配置' },
]

export const NAV_GROUPS = [...new Set(NAV_ITEMS.map(item => item.group))]
export const PAGE_KEYS = new Set(NAV_ITEMS.map(item => item.key))
export const NAV_ITEMS_BY_KEY = Object.fromEntries(NAV_ITEMS.map(item => [item.key, item]))
