export const revenueData = [
  { month: "Jan", revenue: 842000, sales: 12400, orders: 3820, profit: 194000 },
  { month: "Feb", revenue: 910000, sales: 13800, orders: 4100, profit: 218000 },
  { month: "Mar", revenue: 885000, sales: 13200, orders: 3960, profit: 207000 },
  { month: "Apr", revenue: 1020000, sales: 15600, orders: 4550, profit: 248000 },
  { month: "May", revenue: 1140000, sales: 17200, orders: 5010, profit: 279000 },
  { month: "Jun", revenue: 1080000, sales: 16400, orders: 4780, profit: 261000 },
  { month: "Jul", revenue: 1230000, sales: 18700, orders: 5420, profit: 301000 },
  { month: "Aug", revenue: 1190000, sales: 18100, orders: 5280, profit: 291000 },
  { month: "Sep", revenue: 1380000, sales: 21000, orders: 6100, profit: 341000 },
  { month: "Oct", revenue: 1520000, sales: 23200, orders: 6740, profit: 378000 },
  { month: "Nov", revenue: 2210000, sales: 33700, orders: 9820, profit: 552000 },
  { month: "Dec", revenue: 2847000, sales: 43400, orders: 12640, profit: 684000 },
];

export const categoryData = [
  { name: "Electronics", revenue: 1240000, growth: 23.4, share: 43.6 },
  { name: "Apparel", revenue: 620000, growth: 8.1, share: 21.8 },
  { name: "Home & Garden", revenue: 480000, growth: 12.7, share: 16.9 },
  { name: "Sports", revenue: 310000, growth: 5.2, share: 10.9 },
  { name: "Beauty", revenue: 197000, growth: 18.9, share: 6.9 },
];

export const regionalData = [
  { region: "North America", revenue: 1340000, growth: 16.2 },
  { region: "Europe", revenue: 820000, growth: 9.4 },
  { region: "Asia Pacific", revenue: 480000, growth: 28.7 },
  { region: "Latin America", revenue: 140000, growth: -4.2 },
  { region: "Middle East", revenue: 67000, growth: 41.8 },
];

export const kpis = {
  revenue: { value: 2847000, change: 14.8, label: "Revenue", prefix: "$", period: "vs last month" },
  sales: { value: 43400, change: 8.3, label: "Sales", period: "vs last month" },
  orders: { value: 12640, change: 12.1, label: "Orders", period: "vs last month" },
  customers: { value: 8920, change: 6.7, label: "New Customers", period: "vs last month" },
  profit: { value: 684000, change: 18.2, label: "Profit", prefix: "$", period: "vs last month" },
};

export const sparklineData = {
  revenue: [64, 71, 68, 78, 87, 83, 94, 91, 106, 117, 169, 218].map((v, i) => ({ v })),
  sales: [950, 1060, 1010, 1200, 1320, 1260, 1440, 1390, 1610, 1780, 2590, 3340].map((v) => ({ v })),
  orders: [292, 315, 303, 349, 384, 367, 416, 405, 469, 517, 753, 971].map((v) => ({ v })),
  customers: [680, 740, 710, 820, 900, 860, 980, 950, 1080, 1190, 1730, 2230].map((v) => ({ v })),
  profit: [149, 168, 159, 191, 214, 201, 231, 224, 261, 290, 424, 526].map((v) => ({ v })),
};

export const insights = [
  {
    id: "1",
    title: "Electronics revenue is growing 2.3× faster than other categories",
    type: "Growth",
    severity: "high",
    metric: "Electronics Revenue",
    magnitude: "+23.4%",
    confidence: 94,
    description: "Electronics generated $1.24M last month — significantly outperforming the portfolio average of +10.2%. Growth has accelerated for 4 consecutive months.",
    affectedPeriod: "Oct – Dec 2025",
    detectedAt: "2 hours ago",
    chart: "trend",
    tags: ["Electronics", "Revenue", "Category"],
  },
  {
    id: "2",
    title: "Sales in Latin America dropped below expected seasonal trend",
    type: "Anomaly",
    severity: "medium",
    metric: "Latin America Sales",
    magnitude: "-4.2%",
    confidence: 87,
    description: "Latin American revenue declined 4.2% despite the regional market growing 6.1% in the same period. The deviation is statistically significant (p < 0.01).",
    affectedPeriod: "Dec 2025",
    detectedAt: "4 hours ago",
    chart: "bar",
    tags: ["Latin America", "Anomaly", "Sales"],
  },
  {
    id: "3",
    title: "Beauty category showing strong momentum — opportunity to scale",
    type: "Opportunity",
    severity: "medium",
    metric: "Beauty Revenue",
    magnitude: "+18.9%",
    confidence: 81,
    description: "Beauty is the second-fastest growing category at 18.9% MoM. Current inventory allocation may be limiting growth. A 10% increase in ad spend could yield an estimated $42K additional revenue.",
    affectedPeriod: "Nov – Dec 2025",
    detectedAt: "6 hours ago",
    chart: "trend",
    tags: ["Beauty", "Opportunity", "Growth"],
  },
  {
    id: "4",
    title: "Customer acquisition cost increased while conversion rate held",
    type: "Risk",
    severity: "low",
    metric: "CAC",
    magnitude: "+8.7%",
    confidence: 76,
    description: "Average CAC rose from $18.40 to $20.00. Conversion rates remained stable at 3.2%, suggesting the increase is driven by higher media costs rather than campaign underperformance.",
    affectedPeriod: "Dec 2025",
    detectedAt: "1 day ago",
    chart: "line",
    tags: ["Marketing", "CAC", "Risk"],
  },
];

export const anomalies = [
  {
    id: "a1",
    metric: "Revenue",
    date: "Dec 3, 2025",
    actual: "$41,200",
    expected: "$68,400",
    deviation: "-39.7%",
    severity: "high",
    explanation: "Revenue dropped significantly on this date — possibly related to a payment gateway outage reported between 14:00–18:00 UTC.",
  },
  {
    id: "a2",
    metric: "Orders",
    date: "Nov 28, 2025",
    actual: "2,840",
    expected: "1,920",
    deviation: "+47.9%",
    severity: "low",
    explanation: "Order spike consistent with Black Friday promotional period. No anomaly from a business perspective.",
  },
  {
    id: "a3",
    metric: "Avg Order Value",
    date: "Dec 10, 2025",
    actual: "$127",
    expected: "$94",
    deviation: "+35.1%",
    severity: "low",
    explanation: "Elevated by a single B2B order of $124,000. Excluding this, AOV was $89 — within normal range.",
  },
];

export const prescriptions = [
  {
    id: "p1",
    title: "Reallocate inventory from Sports to Electronics",
    problem: "Sports category is overstocked by ~28% relative to sell-through rate. Electronics is supply-constrained.",
    evidence: "Sports inventory turnover: 4.2× (target 6×). Electronics stockout rate: 14% of SKUs.",
    action: "Transfer 20% of open-to-buy budget from Sports to Electronics for Q1 2026.",
    impact: { revenue: "+$84,000", cost: "-$12,000", difficulty: "Medium", risk: "Low" },
    priority: "High",
    confidence: 89,
    alternatives: ["Increase Sports markdown to accelerate sell-through", "Explore dropship options for Electronics"],
  },
  {
    id: "p2",
    title: "Increase Beauty category ad spend by 10–15%",
    problem: "Beauty is showing strong organic growth but may be leaving revenue on the table with current ad budget.",
    evidence: "Beauty ROAS: 4.8× (highest across all categories). Category growth: +18.9% MoM.",
    action: "Increase Beauty digital ad budget from $18,000 to $21,000/month in Q1 2026.",
    impact: { revenue: "+$42,000", cost: "+$3,000", difficulty: "Low", risk: "Low" },
    priority: "High",
    confidence: 81,
    alternatives: ["Launch Beauty loyalty program", "Add Beauty bundles to increase AOV"],
  },
  {
    id: "p3",
    title: "Investigate and address Latin America conversion drop",
    problem: "Latin American revenue declined despite market growth, suggesting a competitive or operational issue.",
    evidence: "Conversion rate in LatAm: 1.8% (global average: 3.2%). Competitor pricing down 12% in region.",
    action: "Conduct pricing audit and consider selective price matching for top 20 SKUs in LatAm.",
    impact: { revenue: "+$28,000", cost: "-$8,000", difficulty: "High", risk: "Medium" },
    priority: "Medium",
    confidence: 72,
    alternatives: ["Launch LatAm-specific promotional campaign", "Partner with regional logistics provider"],
  },
];

export const historyItems = [
  { id: "h1", type: "Analytics", title: "Which product category generated the highest revenue in Q3?", date: "2 hours ago", source: "Sales DB", summary: "Electronics led Q3 with $3.72M revenue (+23.4% YoY)" },
  { id: "h2", type: "Insight", title: "Detected anomaly in Dec 3 revenue data", date: "4 hours ago", source: "Auto-scan", summary: "Payment gateway outage caused 39.7% revenue shortfall" },
  { id: "h3", type: "Prediction", title: "Q1 2026 revenue forecast", date: "Yesterday", source: "Sales DB", summary: "Projected Q1 revenue: $8.4M (+12.3% QoQ)" },
  { id: "h4", type: "Prescription", title: "Inventory reallocation recommendation", date: "Yesterday", source: "Inventory DB", summary: "Transfer 20% budget from Sports to Electronics" },
  { id: "h5", type: "Hypothesis", title: "Does increasing discounts increase sales?", date: "2 days ago", source: "Sales DB", summary: "Supported with high confidence (p < 0.001, r² = 0.71)" },
  { id: "h6", type: "Analytics", title: "Compare revenue between North America and Europe", date: "3 days ago", source: "Sales DB", summary: "NA revenue 1.63× higher; EU growing faster at +9.4% vs +6.2%" },
  { id: "h7", type: "Analytics", title: "What is the average order value by customer segment?", date: "3 days ago", source: "CRM DB", summary: "Enterprise: $284, SMB: $127, Consumer: $67" },
  { id: "h8", type: "Insight", title: "Beauty category momentum opportunity", date: "4 days ago", source: "Auto-scan", summary: "Beauty showing 18.9% MoM growth with room to scale" },
];

export const forecastData = [
  { month: "Jul", actual: 1230000, forecast: null, upper: null, lower: null },
  { month: "Aug", actual: 1190000, forecast: null, upper: null, lower: null },
  { month: "Sep", actual: 1380000, forecast: null, upper: null, lower: null },
  { month: "Oct", actual: 1520000, forecast: null, upper: null, lower: null },
  { month: "Nov", actual: 2210000, forecast: null, upper: null, lower: null },
  { month: "Dec", actual: 2847000, forecast: 2847000, upper: 2847000, lower: 2847000 },
  { month: "Jan", actual: null, forecast: 2640000, upper: 2920000, lower: 2360000 },
  { month: "Feb", actual: null, forecast: 2480000, upper: 2820000, lower: 2140000 },
  { month: "Mar", actual: null, forecast: 2720000, upper: 3140000, lower: 2300000 },
  { month: "Apr", actual: null, forecast: 3010000, upper: 3520000, lower: 2500000 },
  { month: "May", actual: null, forecast: 3290000, upper: 3880000, lower: 2700000 },
  { month: "Jun", actual: null, forecast: 3580000, upper: 4260000, lower: 2900000 },
];

export const copilotMessages: {
  id: string;
  role: "user" | "assistant";
  content: string;
  type: "text" | "rich";
  timestamp: string;
  chartData?: { month: string; value: number }[];
}[] = [
  {
    id: "c1",
    role: "assistant",
    content: "Hello! I'm ARIA, your AI analytics assistant. I have access to your connected data sources and can help you explore your business data, discover insights, and make better decisions. What would you like to know?",
    type: "text",
    timestamp: "10:00 AM",
  },
  {
    id: "c2",
    role: "user",
    content: "Show me revenue for Electronics last quarter.",
    type: "text",
    timestamp: "10:02 AM",
  },
  {
    id: "c3",
    role: "assistant",
    content: "Electronics generated **$3.72M** in Q3 2025, representing a **23.4% increase** year-over-year. It was the top-performing category by both absolute revenue and growth rate.",
    type: "rich",
    timestamp: "10:02 AM",
    chartData: [
      { month: "Jul", value: 290000 },
      { month: "Aug", value: 310000 },
      { month: "Sep", value: 380000 },
      { month: "Oct", value: 420000 },
      { month: "Nov", value: 610000 },
      { month: "Dec", value: 810000 },
    ],
  },
  {
    id: "c4",
    role: "user",
    content: "Why did it decrease in August?",
    type: "text",
    timestamp: "10:03 AM",
  },
  {
    id: "c5",
    role: "assistant",
    content: "The August dip in Electronics revenue (from $310K to... wait, it actually increased from $290K in July to $310K in August). Looking at the data more carefully: Electronics grew consistently throughout Q3. The slight moderation in August growth rate (vs July) was likely due to a normal post-Prime Day cooldown — a well-documented seasonal pattern in consumer electronics.",
    type: "text",
    timestamp: "10:03 AM",
  },
];

export const dbConnections = [
  { id: "db1", name: "Sales Database", type: "PostgreSQL", status: "connected", tables: 24, lastSync: "2 minutes ago", health: 99.8 },
  { id: "db2", name: "CRM Database", type: "MySQL", status: "connected", tables: 18, lastSync: "5 minutes ago", health: 99.2 },
  { id: "db3", name: "Inventory DB", type: "PostgreSQL", status: "connected", tables: 12, lastSync: "1 hour ago", health: 97.4 },
  { id: "db4", name: "Marketing Analytics", type: "BigQuery", status: "warning", tables: 8, lastSync: "3 hours ago", health: 84.1 },
];

export const tableSchema = [
  { name: "orders", rows: "52,840", columns: 14, description: "Customer order records" },
  { name: "products", rows: "4,210", columns: 22, description: "Product catalog with pricing" },
  { name: "customers", rows: "94,620", columns: 18, description: "Customer profiles and segments" },
  { name: "transactions", rows: "284,100", columns: 11, description: "Payment transactions" },
  { name: "inventory", rows: "4,210", columns: 16, description: "Real-time inventory levels" },
  { name: "categories", rows: "48", columns: 8, description: "Product category hierarchy" },
];
