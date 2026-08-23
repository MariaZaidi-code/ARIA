// =========================================================
// ARIA API SERVICE
// =========================================================
//
// FRONTEND DEVELOPMENT VERSION
//
// Current:
// - Schema Agent uses mock Northwind schema.
// - Goal Agent uses simulated responses.
// - Analytics results use simulated processed data.
//
// Later:
// React
//   ↓
// FastAPI
//   ↓
// Real Schema / Goal / Insight Agents
// =========================================================

import northwindSchema from "../data/schema_mapping_northwind_latest.json";

const API_BASE_URL = "http://localhost:8000";

// =========================================================
// DEVELOPMENT SETTINGS
// =========================================================

const SCHEMA_AGENT_DELAY_MS = 1400;
const GOAL_AGENT_DELAY_MS = 1300;
const ANALYTICS_DELAY_MS = 1000;

const SIMULATE_SCHEMA_FAILURE = false;
const SIMULATE_GOAL_FAILURE = false;

// =========================================================
// DAY 7 - INSIGHT AGENT FAILURE TEST
// =========================================================
//
// Set this to true only when testing Step 11B.
//
// First Insight Agent attempt:
// → fails
//
// Retry:
// → succeeds automatically
//
// After testing, change it back to false.
// =========================================================

const SIMULATE_INSIGHT_FAILURE_ONCE = false;

let hasSimulatedInsightFailure = false;

// =========================================================
// DAY 8 - FEEDBACK AGENT FAILURE TEST
// =========================================================

const SIMULATE_FEEDBACK_FAILURE_ONCE = false;

let hasSimulatedFeedbackFailure = false;

// =========================================================
// HELPER
// =========================================================

const delay = (milliseconds) => {
  return new Promise((resolve) => {
    setTimeout(resolve, milliseconds);
  });
};

// =========================================================
// AUTHENTICATION
// =========================================================

export const loginUser = async (email, password) => {
  void password;

  console.log("Login request prepared for:", email);

  return {
    success: true,
    email,
  };
};

// =========================================================
// DATABASE CONNECTION
// =========================================================

export const connectDatabase = async (databaseDetails) => {
  console.log("Database connection request prepared.", databaseDetails);

  return {
    success: true,
    databaseType: databaseDetails?.type || null,
  };
};

// =========================================================
// SCHEMA AGENT
// =========================================================

export const fetchSchema = async () => {
  console.log("Schema Agent started...");

  await delay(SCHEMA_AGENT_DELAY_MS);

  if (SIMULATE_SCHEMA_FAILURE) {
    throw new Error(
      "Schema Agent failed to analyze the connected data source.",
    );
  }

  console.log("Schema Agent completed successfully.");

  return {
    success: true,
    data: northwindSchema,
  };
};

// =========================================================
// NORTHWIND QUESTION SUGGESTIONS
// =========================================================

const NORTHWIND_QUESTION_SUGGESTIONS = [
  "Analyze overall sales performance",
  "Show me monthly sales trends",
  "Show me revenue growth over time",
  "Which products generate the most revenue?",
  "Who are our top customers by total sales?",
  "Show me sales by product category",
  "Show me orders by country",
  "Show the relationship between product price and quantity sold",
  "Which employees processed the most orders?",
  "Which products are low in stock?",
  "Compare sales across different months",
  "Show me the highest value orders",
  "Which suppliers provide the most products?",
];

// =========================================================
// QUESTION SUGGESTIONS
// =========================================================

export const getQuestionSuggestions = async (question, sourceContext = {}) => {
  const searchText = question?.trim().toLowerCase() || "";

  const isNorthwind =
    sourceContext?.sourceType === "postgresql" &&
    sourceContext?.databaseName?.trim().toLowerCase() === "northwind";

  if (!isNorthwind) {
    return {
      success: true,
      data: [],
    };
  }

  if (searchText === "") {
    return {
      success: true,
      data: NORTHWIND_QUESTION_SUGGESTIONS.slice(0, 5),
    };
  }

  const searchWords = searchText.split(/\s+/).filter((word) => word.length > 2);

  const matchedSuggestions = NORTHWIND_QUESTION_SUGGESTIONS.filter(
    (suggestion) => {
      const suggestionText = suggestion.toLowerCase();

      return searchWords.some((word) => suggestionText.includes(word));
    },
  );

  const suggestions =
    matchedSuggestions.length > 0
      ? matchedSuggestions
      : NORTHWIND_QUESTION_SUGGESTIONS;

  return {
    success: true,
    data: suggestions.slice(0, 5),
  };
};

// =========================================================
// QUESTION CORRECTION
// =========================================================

// =========================================================
// QUESTION CORRECTION - FUZZY MATCHING
// =========================================================
//
// FRONTEND DEVELOPMENT VERSION
//
// This corrects likely spelling mistakes in:
//
// 1. Normal question words
//    show, give, tell, please, which, where, etc.
//
// 2. Business / analytics words
//    sales, revenue, customers, category, orders, etc.
//
// Later, the real Goal Agent / LLM can perform
// context-aware correction using the connected schema.
// =========================================================

// =========================================================
// ARIA QUESTION VOCABULARY
// =========================================================

const ARIA_QUESTION_VOCABULARY = [
  // -------------------------------------------------------
  // NORMAL QUESTION / COMMAND WORDS
  // -------------------------------------------------------

  "show",
  "give",
  "tell",
  "please",
  "find",
  "list",
  "want",
  "need",

  "what",
  "which",
  "where",
  "when",
  "why",
  "how",

  "this",
  "that",
  "these",
  "those",

  "from",
  "with",
  "into",
  "over",
  "between",
  "about",

  "most",
  "more",
  "less",
  "than",

  "have",
  "has",
  "does",
  "generate",

  "compare",
  "analyze",
  "analyse",
  "analysis",

  "display",
  "calculate",
  "identify",
  "explain",

  "total",
  "average",
  "highest",
  "lowest",
  "best",
  "top",

  "all",
  "each",
  "different",
  "overall",

  // -------------------------------------------------------
  // SALES / BUSINESS ANALYTICS WORDS
  // -------------------------------------------------------

  "sale",
  "sales",

  "revenue",
  "revenues",

  "growth",

  "product",
  "products",

  "customer",
  "customers",

  "category",
  "categories",

  "order",
  "orders",

  "country",
  "countries",

  "price",
  "prices",

  "quantity",
  "quantities",

  "stock",
  "inventory",

  "supplier",
  "suppliers",

  "employee",
  "employees",

  "month",
  "months",
  "monthly",

  "year",
  "years",
  "yearly",

  "week",
  "weeks",
  "weekly",

  "day",
  "days",
  "daily",

  "trend",
  "trends",

  "performance",

  "value",
  "values",

  "amount",
  "amounts",

  "profit",
  "profits",

  "cost",
  "costs",

  "margin",
  "margins",

  "market",
  "markets",

  "region",
  "regions",

  "store",
  "stores",

  "unit",
  "units",

  "sold",

  "purchase",
  "purchases",

  "transaction",
  "transactions",

  "data",
  "report",
  "reports",

  "chart",
  "charts",

  "dashboard",
  "dashboards",
];

// =========================================================
// DAMERAU-LEVENSHTEIN DISTANCE
// =========================================================
//
// Measures how different two words are.
//
// It supports:
//
// Missing letters:
//   "revenu" → "revenue"
//
// Wrong letters:
//   "catagory" → "category"
//
// Extra letters:
//   "orderrs" → "orders"
//
// Swapped letters:
//   "waht" → "what"
//   "shwo" → "show"
// =========================================================

const getDamerauLevenshteinDistance = (firstWord, secondWord) => {
  const first = firstWord.toLowerCase();

  const second = secondWord.toLowerCase();

  const rows = first.length + 1;

  const columns = second.length + 1;

  const matrix = Array.from(
    {
      length: rows,
    },
    () => Array(columns).fill(0),
  );

  // First column
  for (let row = 0; row < rows; row += 1) {
    matrix[row][0] = row;
  }

  // First row
  for (let column = 0; column < columns; column += 1) {
    matrix[0][column] = column;
  }

  // Calculate distance
  for (let row = 1; row < rows; row += 1) {
    for (let column = 1; column < columns; column += 1) {
      const cost = first[row - 1] === second[column - 1] ? 0 : 1;

      matrix[row][column] = Math.min(
        // Delete
        matrix[row - 1][column] + 1,

        // Insert
        matrix[row][column - 1] + 1,

        // Replace
        matrix[row - 1][column - 1] + cost,
      );

      // ---------------------------------------------------
      // TRANSPOSED LETTERS
      // Example:
      // "waht" → "what"
      // ---------------------------------------------------

      if (
        row > 1 &&
        column > 1 &&
        first[row - 1] === second[column - 2] &&
        first[row - 2] === second[column - 1]
      ) {
        matrix[row][column] = Math.min(
          matrix[row][column],

          matrix[row - 2][column - 2] + 1,
        );
      }
    }
  }

  return matrix[first.length][second.length];
};

// =========================================================
// CALCULATE WORD SIMILARITY
// =========================================================

const getWordSimilarity = (word, candidate, distance) => {
  const longestLength = Math.max(word.length, candidate.length);

  if (longestLength === 0) {
    return 1;
  }

  return 1 - distance / longestLength;
};

// =========================================================
// FIND CLOSEST ARIA WORD
// =========================================================

const findClosestARIAWord = (word) => {
  const normalizedWord = word.toLowerCase();

  // -------------------------------------------------------
  // Do not fuzzy-correct extremely short words.
  //
  // Examples:
  // me
  // by
  // to
  // of
  // in
  // on
  //
  // They are too short for reliable fuzzy matching.
  // -------------------------------------------------------

  if (normalizedWord.length < 3) {
    return null;
  }

  // -------------------------------------------------------
  // Word is already valid
  // -------------------------------------------------------

  if (ARIA_QUESTION_VOCABULARY.includes(normalizedWord)) {
    return null;
  }

  let bestMatch = null;

  let bestDistance = Infinity;

  let bestSimilarity = 0;

  // -------------------------------------------------------
  // CHECK ALL POSSIBLE WORDS
  // -------------------------------------------------------

  for (const candidate of ARIA_QUESTION_VOCABULARY) {
    const lengthDifference = Math.abs(normalizedWord.length - candidate.length);

    // Avoid comparing words whose
    // lengths are extremely different.
    if (lengthDifference > 2) {
      continue;
    }

    const distance = getDamerauLevenshteinDistance(normalizedWord, candidate);

    const similarity = getWordSimilarity(normalizedWord, candidate, distance);

    if (
      distance < bestDistance ||
      (distance === bestDistance && similarity > bestSimilarity)
    ) {
      bestMatch = candidate;

      bestDistance = distance;

      bestSimilarity = similarity;
    }
  }

  if (!bestMatch) {
    return null;
  }

  // =====================================================
  // CONFIDENCE RULES
  // =====================================================

  // 3-letter words:
  // maximum 1 mistake
  //
  // Example:
  // hwo → how

  if (normalizedWord.length === 3) {
    if (bestDistance <= 1 && bestSimilarity >= 0.65) {
      return bestMatch;
    }

    return null;
  }

  // 4-letter words:
  // maximum 1 mistake
  //
  // Examples:
  // shwo → show
  // waht → what

  if (normalizedWord.length === 4) {
    if (bestDistance <= 1 && bestSimilarity >= 0.7) {
      return bestMatch;
    }

    return null;
  }

  // 5-letter words:
  // allow up to 2 mistakes.
  //
  // Example:
  // sails → sales

  if (normalizedWord.length === 5) {
    if (bestDistance <= 2 && bestSimilarity >= 0.6) {
      return bestMatch;
    }

    return null;
  }

  // 6+ letter words:
  // maximum 2 mistakes.
  //
  // Examples:
  // catagory → category
  // costumer → customer
  // revanue → revenue

  if (normalizedWord.length >= 6) {
    if (bestDistance <= 2 && bestSimilarity >= 0.7) {
      return bestMatch;
    }
  }

  return null;
};

// =========================================================
// PRESERVE ORIGINAL CAPITALIZATION
// =========================================================

const preserveWordCase = (originalWord, replacement) => {
  // Entire word uppercase
  if (originalWord === originalWord.toUpperCase()) {
    return replacement.toUpperCase();
  }

  // First letter uppercase
  if (originalWord[0] === originalWord[0].toUpperCase()) {
    return replacement.charAt(0).toUpperCase() + replacement.slice(1);
  }

  return replacement;
};

// =========================================================
// CORRECT FULL USER QUESTION
// =========================================================

const getQuestionCorrection = (question) => {
  if (!question || !question.trim()) {
    return null;
  }

  let correctionMade = false;

  const correctedQuestion = question.replace(
    /\b[A-Za-z]+\b/g,

    (word) => {
      const replacement = findClosestARIAWord(word);

      // No confident correction
      if (!replacement) {
        return word;
      }

      // Same word somehow returned
      if (replacement.toLowerCase() === word.toLowerCase()) {
        return word;
      }

      correctionMade = true;

      return preserveWordCase(word, replacement);
    },
  );

  // Nothing changed
  if (!correctionMade) {
    return null;
  }

  return correctedQuestion;
};

// =========================================================
// GOAL AGENT
// =========================================================

export const analyzeQuestion = async (
  question,
  selectedLLM,
  sourceContext = {},
) => {
  console.log("Goal Agent started:", {
    question,
    selectedLLM,
    sourceContext,
  });

  await delay(GOAL_AGENT_DELAY_MS);

  if (SIMULATE_GOAL_FAILURE) {
    throw new Error("Goal Agent could not process this business question.");
  }

  const correction = getQuestionCorrection(question);

  const normalizedQuestion = (correction || question).trim().toLowerCase();

  // =====================================================
  // OVERALL SALES PERFORMANCE
  // =====================================================

  if (
    normalizedQuestion.includes("sales") &&
    (normalizedQuestion.includes("overall") ||
      normalizedQuestion.includes("complete") ||
      normalizedQuestion.includes("summary") ||
      normalizedQuestion.includes("performance"))
  ) {
    return {
      success: true,

      data: {
        originalQuestion: question,

        correctedQuestion: correction,

        interpretedGoal:
          "Provide a broad analysis of overall sales performance across time, products, categories, customers, and markets.",

        goalType: "overall_sales_analysis",

        relevantTables: [
          "orders",
          "order_details",
          "products",
          "categories",
          "customers",
        ],

        joinPlan: [
          "orders.order_id → order_details.order_id",
          "order_details.product_id → products.product_id",
          "products.category_id → categories.category_id",
          "orders.customer_id → customers.customer_id",
        ],

        generatedSql: `
-- ARIA broad analysis plan

-- Monthly sales
SELECT
  DATE_TRUNC('month', o.order_date) AS month,
  SUM(od.unit_price * od.quantity) AS total_sales
FROM orders o
JOIN order_details od
  ON o.order_id = od.order_id
GROUP BY DATE_TRUNC('month', o.order_date);

-- Additional aggregations are prepared for
-- product, category, customer, and country analysis.
          `.trim(),

        preprocessing: [
          "Calculate sales value from unit price × quantity",
          "Aggregate sales across time periods",
          "Aggregate revenue by product and category",
          "Calculate order distribution across countries",
          "Prepare product price and quantity relationships",
          "Prepare multiple analytical datasets for the Insight Agent",
        ],

        processedDataSummary: {
          rowCount: 42,

          columns: [
            "sales",
            "revenue",
            "product",
            "category",
            "country",
            "price",
            "quantity",
          ],
        },

        nextAgent: "Insight Agent",
      },
    };
  }

  // =====================================================
  // PRICE VS QUANTITY RELATIONSHIP
  // =====================================================

  if (
    normalizedQuestion.includes("price") &&
    normalizedQuestion.includes("quantity")
  ) {
    return {
      success: true,

      data: {
        originalQuestion: question,

        correctedQuestion: correction,

        interpretedGoal:
          "Analyze the relationship between product price and quantity sold.",

        goalType: "relationship_analysis",

        relevantTables: ["products", "order_details"],

        joinPlan: ["products.product_id → order_details.product_id"],

        generatedSql: `
SELECT
  p.product_name,
  p.unit_price AS product_price,
  SUM(od.quantity) AS quantity_sold
FROM products p
JOIN order_details od
  ON p.product_id = od.product_id
GROUP BY
  p.product_name,
  p.unit_price
ORDER BY product_price;
          `.trim(),

        preprocessing: [
          "Use product unit price as the X variable",
          "Aggregate quantities sold for every product",
          "Match each product price with total quantity sold",
          "Prepare numeric pairs for relationship analysis",
        ],

        processedDataSummary: {
          rowCount: 10,

          columns: ["product_price", "quantity_sold"],
        },

        nextAgent: "Insight Agent",
      },
    };
  }

  // =====================================================
  // SALES BY CATEGORY
  // =====================================================

  if (
    normalizedQuestion.includes("sales") &&
    normalizedQuestion.includes("category")
  ) {
    return {
      success: true,

      data: {
        originalQuestion: question,

        correctedQuestion: correction,

        interpretedGoal:
          "Compare how total sales are distributed across product categories.",

        goalType: "category_composition",

        relevantTables: ["categories", "products", "order_details"],

        joinPlan: [
          "categories.category_id → products.category_id",
          "products.product_id → order_details.product_id",
        ],

        generatedSql: `
SELECT
  c.category_name,
  SUM(od.unit_price * od.quantity) AS total_sales
FROM categories c
JOIN products p
  ON c.category_id = p.category_id
JOIN order_details od
  ON p.product_id = od.product_id
GROUP BY c.category_name
ORDER BY total_sales DESC;
          `.trim(),

        preprocessing: [
          "Calculate sales value for each order line",
          "Associate each product with its category",
          "Aggregate sales by product category",
          "Calculate category contribution to total sales",
        ],

        processedDataSummary: {
          rowCount: 6,

          columns: ["category_name", "total_sales"],
        },

        nextAgent: "Insight Agent",
      },
    };
  }

  // =====================================================
  // ORDERS BY COUNTRY
  // =====================================================

  if (
    normalizedQuestion.includes("orders") &&
    normalizedQuestion.includes("country")
  ) {
    return {
      success: true,

      data: {
        originalQuestion: question,

        correctedQuestion: correction,

        interpretedGoal:
          "Rank countries according to the number of customer orders.",

        goalType: "country_ranking",

        relevantTables: ["orders", "customers"],

        joinPlan: ["customers.customer_id → orders.customer_id"],

        generatedSql: `
SELECT
  c.country,
  COUNT(o.order_id) AS order_count
FROM customers c
JOIN orders o
  ON c.customer_id = o.customer_id
GROUP BY c.country
ORDER BY order_count DESC
LIMIT 10;
          `.trim(),

        preprocessing: [
          "Join orders with customer locations",
          "Group orders by customer country",
          "Count orders for each country",
          "Rank countries from highest to lowest order count",
        ],

        processedDataSummary: {
          rowCount: 10,

          columns: ["country", "order_count"],
        },

        nextAgent: "Insight Agent",
      },
    };
  }

  // =====================================================
  // REVENUE GROWTH
  // =====================================================

  if (
    normalizedQuestion.includes("revenue") &&
    (normalizedQuestion.includes("growth") ||
      normalizedQuestion.includes("over time"))
  ) {
    return {
      success: true,

      data: {
        originalQuestion: question,

        correctedQuestion: correction,

        interpretedGoal:
          "Analyze revenue progression over time and identify the overall growth pattern.",

        goalType: "growth_analysis",

        relevantTables: ["orders", "order_details"],

        joinPlan: ["orders.order_id → order_details.order_id"],

        generatedSql: `
SELECT
  DATE_TRUNC('month', o.order_date) AS month,
  SUM(od.unit_price * od.quantity) AS revenue
FROM orders o
JOIN order_details od
  ON o.order_id = od.order_id
GROUP BY
  DATE_TRUNC('month', o.order_date)
ORDER BY month;
          `.trim(),

        preprocessing: [
          "Use order date as the time dimension",
          "Calculate revenue from unit price × quantity",
          "Aggregate revenue by month",
          "Sort monthly revenue chronologically",
        ],

        processedDataSummary: {
          rowCount: 6,

          columns: ["month", "revenue"],
        },

        nextAgent: "Insight Agent",
      },
    };
  }

  // =====================================================
  // MONTHLY SALES TREND
  // =====================================================

  if (
    normalizedQuestion.includes("sales") &&
    (normalizedQuestion.includes("month") ||
      normalizedQuestion.includes("monthly") ||
      normalizedQuestion.includes("trend"))
  ) {
    return {
      success: true,

      data: {
        originalQuestion: question,

        correctedQuestion: correction,

        interpretedGoal:
          "Analyze monthly sales performance and identify how sales change over time.",

        goalType: "trend_analysis",

        relevantTables: ["orders", "order_details", "products"],

        joinPlan: [
          "orders.order_id → order_details.order_id",
          "order_details.product_id → products.product_id",
        ],

        generatedSql: `
SELECT
  DATE_TRUNC('month', o.order_date) AS month,
  SUM(od.unit_price * od.quantity) AS total_sales
FROM orders o
JOIN order_details od
  ON o.order_id = od.order_id
GROUP BY
  DATE_TRUNC('month', o.order_date)
ORDER BY month;
          `.trim(),

        preprocessing: [
          "Use order_date as the time dimension",
          "Calculate sales from unit price × quantity",
          "Aggregate results by month",
          "Sort months chronologically",
        ],

        processedDataSummary: {
          rowCount: 6,

          columns: ["month", "total_sales"],
        },

        nextAgent: "Insight Agent",
      },
    };
  }

  // =====================================================
  // TOP PRODUCTS
  // =====================================================

  if (
    normalizedQuestion.includes("product") &&
    (normalizedQuestion.includes("top") ||
      normalizedQuestion.includes("revenue") ||
      normalizedQuestion.includes("best"))
  ) {
    return {
      success: true,

      data: {
        originalQuestion: question,

        correctedQuestion: correction,

        interpretedGoal:
          "Identify the products generating the highest sales revenue.",

        goalType: "ranking_analysis",

        relevantTables: ["products", "order_details"],

        joinPlan: ["products.product_id → order_details.product_id"],

        generatedSql: `
SELECT
  p.product_name,
  SUM(od.unit_price * od.quantity) AS total_revenue
FROM products p
JOIN order_details od
  ON p.product_id = od.product_id
GROUP BY p.product_name
ORDER BY total_revenue DESC
LIMIT 10;
          `.trim(),

        preprocessing: [
          "Calculate revenue for every order line",
          "Aggregate revenue by product",
          "Sort products from highest to lowest revenue",
          "Return the top 10 products",
        ],

        processedDataSummary: {
          rowCount: 10,

          columns: ["product_name", "total_revenue"],
        },

        nextAgent: "Insight Agent",
      },
    };
  }

  // =====================================================
  // TOP CUSTOMERS
  // =====================================================

  if (
    normalizedQuestion.includes("customer") &&
    (normalizedQuestion.includes("top") ||
      normalizedQuestion.includes("sales") ||
      normalizedQuestion.includes("revenue"))
  ) {
    return {
      success: true,

      data: {
        originalQuestion: question,

        correctedQuestion: correction,

        interpretedGoal: "Rank customers according to their total sales value.",

        goalType: "customer_ranking",

        relevantTables: ["customers", "orders", "order_details"],

        joinPlan: [
          "customers.customer_id → orders.customer_id",
          "orders.order_id → order_details.order_id",
        ],

        generatedSql: `
SELECT
  c.company_name,
  SUM(od.unit_price * od.quantity) AS total_sales
FROM customers c
JOIN orders o
  ON c.customer_id = o.customer_id
JOIN order_details od
  ON o.order_id = od.order_id
GROUP BY c.company_name
ORDER BY total_sales DESC
LIMIT 10;
          `.trim(),

        preprocessing: [
          "Join customers with their orders",
          "Calculate order-line sales value",
          "Aggregate sales by customer",
          "Rank customers by total sales",
        ],

        processedDataSummary: {
          rowCount: 10,

          columns: ["company_name", "total_sales"],
        },

        nextAgent: "Insight Agent",
      },
    };
  }

  // =====================================================
  // AMBIGUOUS QUESTION
  // =====================================================

  return {
    success: true,

    data: {
      originalQuestion: question,

      correctedQuestion: correction,

      interpretedGoal:
        "ARIA understood this as a general business analysis request.",

      goalType: "general_analysis",

      relevantTables: [],

      joinPlan: [],

      generatedSql: null,

      preprocessing: [],

      processedDataSummary: null,

      nextAgent: null,

      clarificationRequired: true,

      clarificationMessage:
        "ARIA needs a little more detail to determine the exact tables and metrics for this question.",
    },
  };
};

// =========================================================
// DAY 6 ANALYTICS RESULT GENERATION
// =========================================================

export const generateAnalyticsResult = async (goalResult) => {
  console.log("Analytics result generation started:", goalResult);

  await delay(ANALYTICS_DELAY_MS);

  if (!goalResult) {
    throw new Error("No Goal Agent result was provided.");
  }

  // =====================================================
  // OVERALL SALES PERFORMANCE - FULL BI DASHBOARD
  // =====================================================

  if (goalResult.goalType === "overall_sales_analysis") {
    const monthlySales = [
      {
        month: "January",
        sales: 85000,
      },
      {
        month: "February",
        sales: 92000,
      },
      {
        month: "March",
        sales: 108000,
      },
      {
        month: "April",
        sales: 97000,
      },
      {
        month: "May",
        sales: 115000,
      },
      {
        month: "June",
        sales: 124000,
      },
    ];

    const categorySales = [
      {
        category: "Beverages",
        sales: 142000,
      },
      {
        category: "Dairy Products",
        sales: 118000,
      },
      {
        category: "Confections",
        sales: 96000,
      },
      {
        category: "Meat/Poultry",
        sales: 86000,
      },
      {
        category: "Seafood",
        sales: 71000,
      },
      {
        category: "Produce",
        sales: 54000,
      },
    ];

    const productRevenue = [
      {
        product: "Côte de Blaye",
        revenue: 62900,
      },
      {
        product: "Thüringer Rostbratwurst",
        revenue: 54500,
      },
      {
        product: "Raclette Courdavault",
        revenue: 48800,
      },
      {
        product: "Tarte au sucre",
        revenue: 47200,
      },
      {
        product: "Camembert Pierrot",
        revenue: 43800,
      },
      {
        product: "Manjimup Dried Apples",
        revenue: 41900,
      },
    ];

    const countryOrders = [
      {
        country: "USA",
        orders: 122,
      },
      {
        country: "Germany",
        orders: 86,
      },
      {
        country: "France",
        orders: 77,
      },
      {
        country: "Brazil",
        orders: 63,
      },
      {
        country: "UK",
        orders: 56,
      },
      {
        country: "Austria",
        orders: 42,
      },
    ];

    const revenueGrowth = [
      {
        month: "January",
        revenue: 76000,
      },
      {
        month: "February",
        revenue: 82500,
      },
      {
        month: "March",
        revenue: 91000,
      },
      {
        month: "April",
        revenue: 96500,
      },
      {
        month: "May",
        revenue: 109000,
      },
      {
        month: "June",
        revenue: 121500,
      },
    ];

    const priceQuantity = [
      {
        product: "Product A",
        price: 12,
        quantity: 780,
      },
      {
        product: "Product B",
        price: 18,
        quantity: 690,
      },
      {
        product: "Product C",
        price: 24,
        quantity: 610,
      },
      {
        product: "Product D",
        price: 31,
        quantity: 540,
      },
      {
        product: "Product E",
        price: 39,
        quantity: 470,
      },
      {
        product: "Product F",
        price: 47,
        quantity: 420,
      },
      {
        product: "Product G",
        price: 56,
        quantity: 355,
      },
      {
        product: "Product H",
        price: 64,
        quantity: 310,
      },
    ];

    return {
      success: true,

      data: {
        resultType: "overall_sales_dashboard",

        kpis: [
          {
            label: "Total Sales",
            value: "$621K",
          },
          {
            label: "Total Orders",
            value: "830",
          },
          {
            label: "Top Product",
            value: "Côte de Blaye",
          },
        ],

        charts: [
          {
            type: "line",

            title: "Monthly Sales Trend",

            xKey: "month",

            yKey: "sales",

            yLabel: "Sales",

            data: monthlySales,
          },

          {
            type: "donut",

            title: "Sales by Product Category",

            nameKey: "category",

            valueKey: "sales",

            yLabel: "Sales",

            data: categorySales,
          },

          {
            type: "horizontal-bar",

            title: "Top Products by Revenue",

            xKey: "product",

            yKey: "revenue",

            xLabel: "Revenue",

            yLabel: "Product",

            data: productRevenue,
          },

          {
            type: "bar",

            title: "Orders by Country",

            xKey: "country",

            yKey: "orders",

            yLabel: "Orders",

            data: countryOrders,
          },

          {
            type: "area",

            title: "Revenue Growth Over Time",

            xKey: "month",

            yKey: "revenue",

            yLabel: "Revenue",

            data: revenueGrowth,
          },

          {
            type: "scatter",

            title: "Product Price vs Quantity Sold",

            xKey: "price",

            yKey: "quantity",

            xLabel: "Product Price",

            yLabel: "Quantity Sold",

            data: priceQuantity,
          },
        ],

        table: {
          columns: [
            {
              key: "month",

              label: "Month",
            },
            {
              key: "sales",

              label: "Sales",
            },
          ],

          rows: monthlySales,
        },
      },
    };
  }

  // =====================================================
  // MONTHLY SALES - MULTI-CHART ANALYSIS
  // =====================================================

  if (goalResult.goalType === "trend_analysis") {
    const monthlyPerformance = [
      {
        month: "January",
        sales: 85000,
        orders: 105,
        averageOrderValue: 809.52,
        growth: null,
      },
      {
        month: "February",
        sales: 92000,
        orders: 112,
        averageOrderValue: 821.43,
        growth: 8.2,
      },
      {
        month: "March",
        sales: 108000,
        orders: 138,
        averageOrderValue: 782.61,
        growth: 17.4,
      },
      {
        month: "April",
        sales: 97000,
        orders: 121,
        averageOrderValue: 801.65,
        growth: -10.2,
      },
      {
        month: "May",
        sales: 115000,
        orders: 146,
        averageOrderValue: 787.67,
        growth: 18.6,
      },
      {
        month: "June",
        sales: 124000,
        orders: 158,
        averageOrderValue: 784.81,
        growth: 7.8,
      },
    ];

    return {
      success: true,

      data: {
        resultType: "sales_trend_dashboard",

        kpis: [
          {
            label: "Total Sales",
            value: "$621K",
          },
          {
            label: "Average Monthly Sales",
            value: "$103.5K",
          },
          {
            label: "Best Month",
            value: "June",
          },
          {
            label: "Total Orders",
            value: "780",
          },
        ],

        charts: [
          {
            type: "line",

            title: "Monthly Sales Trend",

            xKey: "month",

            yKey: "sales",

            yLabel: "Sales",

            data: monthlyPerformance,
          },

          {
            type: "bar",

            title: "Monthly Order Volume",

            xKey: "month",

            yKey: "orders",

            yLabel: "Orders",

            data: monthlyPerformance,
          },

          {
            type: "area",

            title: "Average Order Value by Month",

            xKey: "month",

            yKey: "averageOrderValue",

            yLabel: "Average Order Value",

            data: monthlyPerformance,
          },

          {
            type: "line",

            title: "Month-over-Month Sales Growth",

            xKey: "month",

            yKey: "growth",

            yLabel: "Growth (%)",

            data: monthlyPerformance,
          },
        ],

        table: {
          columns: [
            {
              key: "month",
              label: "Month",
            },
            {
              key: "sales",
              label: "Sales",
            },
            {
              key: "orders",
              label: "Orders",
            },
            {
              key: "averageOrderValue",
              label: "Avg. Order Value",
            },
            {
              key: "growth",
              label: "Growth %",
            },
          ],

          rows: monthlyPerformance,
        },
      },
    };
  }

  // =====================================================
  // REVENUE GROWTH
  // =====================================================

  if (goalResult.goalType === "growth_analysis") {
    const revenuePerformance = [
      {
        month: "January",
        revenue: 76000,
        growth: null,
        cumulativeRevenue: 76000,
      },
      {
        month: "February",
        revenue: 82500,
        growth: 8.6,
        cumulativeRevenue: 158500,
      },
      {
        month: "March",
        revenue: 91000,
        growth: 10.3,
        cumulativeRevenue: 249500,
      },
      {
        month: "April",
        revenue: 96500,
        growth: 6.0,
        cumulativeRevenue: 346000,
      },
      {
        month: "May",
        revenue: 109000,
        growth: 13.0,
        cumulativeRevenue: 455000,
      },
      {
        month: "June",
        revenue: 121500,
        growth: 11.5,
        cumulativeRevenue: 576500,
      },
    ];

    return {
      success: true,

      data: {
        resultType: "revenue_growth_dashboard",

        kpis: [
          {
            label: "Current Revenue",
            value: "$121.5K",
          },
          {
            label: "Starting Revenue",
            value: "$76K",
          },
          {
            label: "Overall Growth",
            value: "59.9%",
          },
          {
            label: "Cumulative Revenue",
            value: "$576.5K",
          },
        ],

        charts: [
          {
            type: "line",

            title: "Revenue Trend Over Time",

            xKey: "month",

            yKey: "revenue",

            xLabel: "Month",

            yLabel: "Revenue",

            data: revenuePerformance,
          },

          {
            type: "bar",

            title: "Month-over-Month Revenue Growth",

            xKey: "month",

            yKey: "growth",

            xLabel: "Month",

            yLabel: "Growth (%)",

            data: revenuePerformance,
          },

          {
            type: "area",

            title: "Cumulative Revenue Growth",

            xKey: "month",

            yKey: "cumulativeRevenue",

            xLabel: "Month",

            yLabel: "Cumulative Revenue",

            data: revenuePerformance,
          },
        ],

        table: {
          columns: [
            {
              key: "month",
              label: "Month",
            },
            {
              key: "revenue",
              label: "Revenue",
            },
            {
              key: "growth",
              label: "Growth %",
            },
            {
              key: "cumulativeRevenue",
              label: "Cumulative Revenue",
            },
          ],

          rows: revenuePerformance,
        },
      },
    };
  }

  // =====================================================
  // TOP PRODUCTS
  // =====================================================

  if (goalResult.goalType === "ranking_analysis") {
    const productPerformance = [
      {
        product: "Côte de Blaye",
        revenue: 62900,
        quantitySold: 280,
        orderCount: 92,
        averageUnitPrice: 224.64,
      },
      {
        product: "Thüringer Rostbratwurst",
        revenue: 54500,
        quantitySold: 340,
        orderCount: 86,
        averageUnitPrice: 160.29,
      },
      {
        product: "Raclette Courdavault",
        revenue: 48800,
        quantitySold: 410,
        orderCount: 81,
        averageUnitPrice: 119.02,
      },
      {
        product: "Tarte au sucre",
        revenue: 47200,
        quantitySold: 390,
        orderCount: 77,
        averageUnitPrice: 121.03,
      },
      {
        product: "Camembert Pierrot",
        revenue: 43800,
        quantitySold: 460,
        orderCount: 74,
        averageUnitPrice: 95.22,
      },
      {
        product: "Manjimup Dried Apples",
        revenue: 41900,
        quantitySold: 510,
        orderCount: 72,
        averageUnitPrice: 82.16,
      },
      {
        product: "Gnocchi di nonna Alice",
        revenue: 39700,
        quantitySold: 495,
        orderCount: 69,
        averageUnitPrice: 80.2,
      },
      {
        product: "Alice Mutton",
        revenue: 38200,
        quantitySold: 430,
        orderCount: 65,
        averageUnitPrice: 88.84,
      },
      {
        product: "Carnarvon Tigers",
        revenue: 36900,
        quantitySold: 370,
        orderCount: 61,
        averageUnitPrice: 99.73,
      },
      {
        product: "Rössle Sauerkraut",
        revenue: 35100,
        quantitySold: 520,
        orderCount: 59,
        averageUnitPrice: 67.5,
      },
    ];

    return {
      success: true,

      data: {
        resultType: "product_performance_dashboard",

        kpis: [
          {
            label: "Top Product",
            value: "Côte de Blaye",
          },
          {
            label: "Top Product Revenue",
            value: "$62.9K",
          },
          {
            label: "Top 10 Revenue",
            value: "$449K",
          },
          {
            label: "Products Compared",
            value: "10",
          },
        ],

        charts: [
          {
            type: "horizontal-bar",

            title: "Top Products by Revenue",

            xKey: "product",

            yKey: "revenue",

            xLabel: "Revenue",

            yLabel: "Product",

            data: productPerformance,
          },

          {
            type: "bar",

            title: "Quantity Sold by Product",

            xKey: "product",

            yKey: "quantitySold",

            xLabel: "Product",

            yLabel: "Quantity Sold",

            data: productPerformance,
          },

          {
            type: "bar",

            title: "Orders Containing Each Product",

            xKey: "product",

            yKey: "orderCount",

            xLabel: "Product",

            yLabel: "Order Count",

            data: productPerformance,
          },

          {
            type: "scatter",

            title: "Average Unit Price vs Product Revenue",

            xKey: "averageUnitPrice",

            yKey: "revenue",

            xLabel: "Average Unit Price",

            yLabel: "Revenue",

            data: productPerformance,
          },
        ],

        table: {
          columns: [
            {
              key: "product",
              label: "Product",
            },
            {
              key: "revenue",
              label: "Revenue",
            },
            {
              key: "quantitySold",
              label: "Quantity Sold",
            },
            {
              key: "orderCount",
              label: "Order Count",
            },
            {
              key: "averageUnitPrice",
              label: "Average Unit Price",
            },
          ],

          rows: productPerformance,
        },
      },
    };
  }

  // =====================================================
  // TOP CUSTOMERS
  // =====================================================

  if (goalResult.goalType === "customer_ranking") {
    const customerPerformance = [
      {
        customer: "QUICK-Stop",
        sales: 117400,
        orderCount: 28,
        averageOrderValue: 4192.86,
      },
      {
        customer: "Ernst Handel",
        sales: 104800,
        orderCount: 30,
        averageOrderValue: 3493.33,
      },
      {
        customer: "Save-a-lot Markets",
        sales: 98200,
        orderCount: 31,
        averageOrderValue: 3167.74,
      },
      {
        customer: "Rattlesnake Canyon Grocery",
        sales: 84600,
        orderCount: 24,
        averageOrderValue: 3525,
      },
      {
        customer: "Hungry Owl All-Night Grocers",
        sales: 79300,
        orderCount: 22,
        averageOrderValue: 3604.55,
      },
      {
        customer: "Hanari Carnes",
        sales: 74100,
        orderCount: 20,
        averageOrderValue: 3705,
      },
      {
        customer: "Königlich Essen",
        sales: 69800,
        orderCount: 19,
        averageOrderValue: 3673.68,
      },
      {
        customer: "Folk och fä HB",
        sales: 65100,
        orderCount: 18,
        averageOrderValue: 3616.67,
      },
      {
        customer: "White Clover Markets",
        sales: 61700,
        orderCount: 17,
        averageOrderValue: 3629.41,
      },
      {
        customer: "Queen Cozinha",
        sales: 58900,
        orderCount: 16,
        averageOrderValue: 3681.25,
      },
    ];

    return {
      success: true,

      data: {
        resultType: "customer_performance_dashboard",

        kpis: [
          {
            label: "Top Customer",
            value: "QUICK-Stop",
          },
          {
            label: "Top Customer Sales",
            value: "$117.4K",
          },
          {
            label: "Highest Order Count",
            value: "31",
          },
          {
            label: "Customers Compared",
            value: "10",
          },
        ],

        charts: [
          {
            type: "horizontal-bar",

            title: "Top Customers by Total Sales",

            xKey: "customer",

            yKey: "sales",

            xLabel: "Total Sales",

            yLabel: "Customer",

            data: customerPerformance,
          },

          {
            type: "bar",

            title: "Orders by Customer",

            xKey: "customer",

            yKey: "orderCount",

            xLabel: "Customer",

            yLabel: "Order Count",

            data: customerPerformance,
          },

          {
            type: "bar",

            title: "Average Order Value by Customer",

            xKey: "customer",

            yKey: "averageOrderValue",

            xLabel: "Customer",

            yLabel: "Average Order Value",

            data: customerPerformance,
          },

          {
            type: "scatter",

            title: "Order Frequency vs Total Sales",

            xKey: "orderCount",

            yKey: "sales",

            xLabel: "Order Count",

            yLabel: "Total Sales",

            data: customerPerformance,
          },
        ],

        table: {
          columns: [
            {
              key: "customer",
              label: "Customer",
            },
            {
              key: "sales",
              label: "Total Sales",
            },
            {
              key: "orderCount",
              label: "Order Count",
            },
            {
              key: "averageOrderValue",
              label: "Average Order Value",
            },
          ],

          rows: customerPerformance,
        },
      },
    };
  }

  // =====================================================
  // SALES BY CATEGORY - FULL BI DASHBOARD
  // =====================================================

  if (goalResult.goalType === "category_composition") {
    const categoryPerformance = [
      {
        category: "Beverages",
        sales: 142000,
        orders: 184,
        averageOrderValue: 771.74,
      },
      {
        category: "Dairy Products",
        sales: 118000,
        orders: 156,
        averageOrderValue: 756.41,
      },
      {
        category: "Confections",
        sales: 96000,
        orders: 133,
        averageOrderValue: 721.8,
      },
      {
        category: "Meat/Poultry",
        sales: 86000,
        orders: 104,
        averageOrderValue: 826.92,
      },
      {
        category: "Seafood",
        sales: 71000,
        orders: 98,
        averageOrderValue: 724.49,
      },
      {
        category: "Produce",
        sales: 54000,
        orders: 72,
        averageOrderValue: 750,
      },
    ];

    return {
      success: true,

      data: {
        resultType: "category_performance_dashboard",

        kpis: [
          {
            label: "Top Category",
            value: "Beverages",
          },
          {
            label: "Top Category Sales",
            value: "$142K",
          },
          {
            label: "Total Category Sales",
            value: "$567K",
          },
          {
            label: "Categories Analyzed",
            value: "6",
          },
        ],

        charts: [
          {
            type: "horizontal-bar",

            title: "Sales by Product Category",

            xKey: "category",

            yKey: "sales",

            xLabel: "Sales",

            yLabel: "Category",

            data: categoryPerformance,
          },

          {
            type: "donut",

            title: "Category Revenue Share",

            nameKey: "category",

            valueKey: "sales",

            yLabel: "Sales",

            data: categoryPerformance,
          },

          {
            type: "bar",

            title: "Orders by Product Category",

            xKey: "category",

            yKey: "orders",

            xLabel: "Category",

            yLabel: "Orders",

            data: categoryPerformance,
          },

          {
            type: "bar",

            title: "Average Order Value by Category",

            xKey: "category",

            yKey: "averageOrderValue",

            xLabel: "Category",

            yLabel: "Average Order Value",

            data: categoryPerformance,
          },
        ],

        table: {
          columns: [
            {
              key: "category",
              label: "Category",
            },
            {
              key: "sales",
              label: "Sales",
            },
            {
              key: "orders",
              label: "Orders",
            },
            {
              key: "averageOrderValue",
              label: "Average Order Value",
            },
          ],

          rows: categoryPerformance,
        },
      },
    };
  }

  // =====================================================
  // ORDERS BY COUNTRY - FULL BI DASHBOARD
  // =====================================================

  if (goalResult.goalType === "country_ranking") {
    const countryPerformance = [
      {
        country: "USA",
        orders: 122,
        sales: 154000,
        customers: 13,
        averageOrderValue: 1262.3,
      },
      {
        country: "Germany",
        orders: 86,
        sales: 118000,
        customers: 11,
        averageOrderValue: 1372.09,
      },
      {
        country: "France",
        orders: 77,
        sales: 103000,
        customers: 10,
        averageOrderValue: 1337.66,
      },
      {
        country: "Brazil",
        orders: 63,
        sales: 79000,
        customers: 9,
        averageOrderValue: 1253.97,
      },
      {
        country: "UK",
        orders: 56,
        sales: 74000,
        customers: 7,
        averageOrderValue: 1321.43,
      },
      {
        country: "Austria",
        orders: 42,
        sales: 68000,
        customers: 5,
        averageOrderValue: 1619.05,
      },
      {
        country: "Sweden",
        orders: 37,
        sales: 47000,
        customers: 5,
        averageOrderValue: 1270.27,
      },
      {
        country: "Canada",
        orders: 32,
        sales: 41000,
        customers: 4,
        averageOrderValue: 1281.25,
      },
      {
        country: "Mexico",
        orders: 28,
        sales: 33000,
        customers: 4,
        averageOrderValue: 1178.57,
      },
      {
        country: "Spain",
        orders: 24,
        sales: 28000,
        customers: 3,
        averageOrderValue: 1166.67,
      },
    ];

    return {
      success: true,

      data: {
        resultType: "country_performance_dashboard",

        kpis: [
          {
            label: "Top Country by Orders",
            value: "USA",
          },
          {
            label: "Highest Order Count",
            value: "122",
          },
          {
            label: "Top Country Sales",
            value: "$154K",
          },
          {
            label: "Countries Compared",
            value: "10",
          },
        ],

        charts: [
          {
            type: "horizontal-bar",

            title: "Orders by Country",

            xKey: "country",

            yKey: "orders",

            xLabel: "Orders",

            yLabel: "Country",

            data: countryPerformance,
          },

          {
            type: "bar",

            title: "Sales by Country",

            xKey: "country",

            yKey: "sales",

            xLabel: "Country",

            yLabel: "Sales",

            data: countryPerformance,
          },

          {
            type: "bar",

            title: "Customers by Country",

            xKey: "country",

            yKey: "customers",

            xLabel: "Country",

            yLabel: "Customers",

            data: countryPerformance,
          },

          {
            type: "scatter",

            title: "Order Volume vs Total Sales",

            xKey: "orders",

            yKey: "sales",

            xLabel: "Orders",

            yLabel: "Total Sales",

            data: countryPerformance,
          },
        ],

        table: {
          columns: [
            {
              key: "country",
              label: "Country",
            },
            {
              key: "orders",
              label: "Orders",
            },
            {
              key: "sales",
              label: "Sales",
            },
            {
              key: "customers",
              label: "Customers",
            },
            {
              key: "averageOrderValue",
              label: "Average Order Value",
            },
          ],

          rows: countryPerformance,
        },
      },
    };
  }

  // =====================================================
  // PRICE VS QUANTITY - FULL BI DASHBOARD
  // =====================================================

  if (goalResult.goalType === "relationship_analysis") {
    const priceQuantityPerformance = [
      {
        product: "Product A",
        price: 12,
        quantity: 780,
        salesValue: 9360,
      },
      {
        product: "Product B",
        price: 18,
        quantity: 690,
        salesValue: 12420,
      },
      {
        product: "Product C",
        price: 24,
        quantity: 610,
        salesValue: 14640,
      },
      {
        product: "Product D",
        price: 31,
        quantity: 540,
        salesValue: 16740,
      },
      {
        product: "Product E",
        price: 39,
        quantity: 470,
        salesValue: 18330,
      },
      {
        product: "Product F",
        price: 47,
        quantity: 420,
        salesValue: 19740,
      },
      {
        product: "Product G",
        price: 56,
        quantity: 355,
        salesValue: 19880,
      },
      {
        product: "Product H",
        price: 64,
        quantity: 310,
        salesValue: 19840,
      },
      {
        product: "Product I",
        price: 76,
        quantity: 255,
        salesValue: 19380,
      },
      {
        product: "Product J",
        price: 89,
        quantity: 210,
        salesValue: 18690,
      },
    ];

    return {
      success: true,

      data: {
        resultType: "price_quantity_dashboard",

        kpis: [
          {
            label: "Products Analyzed",
            value: "10",
          },
          {
            label: "Average Price",
            value: "$45.60",
          },
          {
            label: "Highest Quantity Sold",
            value: "780",
          },
          {
            label: "Relationship",
            value: "Negative",
          },
        ],

        charts: [
          {
            type: "scatter",

            title: "Product Price vs Quantity Sold",

            xKey: "price",

            yKey: "quantity",

            xLabel: "Product Price",

            yLabel: "Quantity Sold",

            data: priceQuantityPerformance,
          },

          {
            type: "horizontal-bar",

            title: "Quantity Sold by Product",

            xKey: "product",

            yKey: "quantity",

            xLabel: "Quantity Sold",

            yLabel: "Product",

            data: priceQuantityPerformance,
          },

          {
            type: "bar",

            title: "Product Price Comparison",

            xKey: "product",

            yKey: "price",

            xLabel: "Product",

            yLabel: "Product Price",

            data: priceQuantityPerformance,
          },

          {
            type: "horizontal-bar",

            title: "Sales Value by Product",

            xKey: "product",

            yKey: "salesValue",

            xLabel: "Sales Value",

            yLabel: "Product",

            data: priceQuantityPerformance,
          },
        ],

        table: {
          columns: [
            {
              key: "product",
              label: "Product",
            },
            {
              key: "price",
              label: "Price",
            },
            {
              key: "quantity",
              label: "Quantity Sold",
            },
            {
              key: "salesValue",
              label: "Sales Value",
            },
          ],

          rows: priceQuantityPerformance,
        },
      },
    };
  }

  // =====================================================
  // NO SUPPORTED ANALYTICS
  // =====================================================

  return {
    success: true,
    data: null,
  };
};
// =========================================================
// DAY 7 - INSIGHT AGENT
// =========================================================
//
// FRONTEND DEVELOPMENT VERSION
//
// Current:
// - Insight Agent uses simulated analytical responses.
// - Responses are based on the Goal Agent analysis type.
// - Dashboard data remains unchanged.
//
// Later:
// React
//   ↓
// FastAPI
//   ↓
// Real Insight Agent
// =========================================================

export const generateInsights = async (goalResult, analyticsResult) => {
  console.log("Insight Agent started:", {
    goalResult,
    analyticsResult,
  });

  // Temporary frontend simulation.
  await delay(1200);

  if (!goalResult) {
    throw new Error("No Goal Agent result was provided to the Insight Agent.");
  }

  if (!analyticsResult) {
    throw new Error("No analytics result was provided to the Insight Agent.");
  }
  // =====================================================
  // DEVELOPMENT TEST - FAIL FIRST INSIGHT ATTEMPT ONCE
  // =====================================================

  if (SIMULATE_INSIGHT_FAILURE_ONCE && !hasSimulatedInsightFailure) {
    hasSimulatedInsightFailure = true;

    throw new Error("Insight Agent test failure. Retry the insight analysis.");
  }

  // =====================================================
  // OVERALL SALES PERFORMANCE
  // =====================================================

  if (goalResult.goalType === "overall_sales_analysis") {
    return {
      success: true,

      data: {
        resultType: "overall_sales_insights",

        keyInsights: [
          {
            title: "Sales strengthened toward the end of the period",

            description:
              "Monthly sales reached their highest level in June at $124K after recovering from the April slowdown.",

            impact: "high",
          },

          {
            title: "Beverages lead category revenue",

            description:
              "Beverages generated the largest category sales contribution, making the category a major driver of overall performance.",

            impact: "high",
          },

          {
            title: "Revenue is concentrated among leading products",

            description:
              "Côte de Blaye is the strongest product in the current comparison, with several premium products contributing a large share of revenue.",

            impact: "medium",
          },
        ],

        trends: [
          {
            title: "Upward sales momentum",

            description:
              "Sales generally rise from January through June despite a temporary decline in April.",

            direction: "up",
          },

          {
            title: "Revenue growth accelerates in the later months",

            description:
              "Revenue increases from $76K in January to $121.5K in June, indicating sustained positive momentum.",

            direction: "up",
          },
        ],

        anomalies: [
          {
            title: "April performance dip",

            description:
              "April breaks the broader upward sales pattern by falling below March before performance rebounds strongly in May.",

            severity: "medium",
          },
        ],

        hypotheses: [
          {
            rank: 1,

            title: "Higher order activity is driving recent sales growth",

            description:
              "The rise in monthly sales may be primarily explained by increasing transaction volume rather than large changes in average order value.",

            confidence: 0.87,

            evidence: [
              "Sales peak in June",
              "Order activity increases across the later months",
              "Average order value remains comparatively stable",
            ],
          },

          {
            rank: 2,

            title:
              "High-value products are disproportionately influencing revenue",

            description:
              "Premium products may be contributing more strongly to revenue than their sales volume alone would suggest.",

            confidence: 0.81,

            evidence: [
              "Côte de Blaye ranks first by revenue",
              "Several top products have comparatively high unit prices",
            ],
          },

          {
            rank: 3,

            title: "Category mix is shaping total sales performance",

            description:
              "The dominance of Beverages and Dairy Products may be an important reason overall sales remain strong.",

            confidence: 0.76,

            evidence: [
              "Beverages lead category sales",
              "Dairy Products are the second-largest category",
            ],
          },
        ],

        recommendations: [
          {
            title: "Protect momentum in the strongest categories",

            description:
              "Prioritize stock availability and promotional support for high-performing categories such as Beverages and Dairy Products.",

            priority: "high",
          },

          {
            title: "Investigate the April slowdown",

            description:
              "Review order volume, customer activity, product availability, and seasonal factors that may explain the temporary decline.",

            priority: "medium",
          },

          {
            title: "Reduce dependence on a small set of top products",

            description:
              "Develop cross-sell or promotional strategies for mid-tier products so revenue growth is less concentrated.",

            priority: "medium",
          },
        ],

        predictions: [
          {
            title: "Near-term sales outlook",

            description:
              "If the recent growth pattern continues, the next period is likely to remain above the early-period sales baseline.",

            confidence: "medium",
          },
        ],

        businessStory:
          "Overall performance is positive. Sales and revenue strengthen across the period, with June producing the strongest monthly result. The business is benefiting from strong category leaders and several high-value products, although the April decline shows that growth is not perfectly stable. The most useful next action is to understand the April slowdown while protecting inventory and commercial focus around the categories and products currently driving the strongest results.",
      },
    };
  }

  // =====================================================
  // MONTHLY SALES TREND
  // =====================================================

  if (goalResult.goalType === "trend_analysis") {
    return {
      success: true,

      data: {
        resultType: "sales_trend_insights",

        keyInsights: [
          {
            title: "June is the strongest sales month",

            description:
              "Monthly sales reach $124K in June, the highest value in the analyzed period.",

            impact: "high",
          },

          {
            title: "Sales recover quickly after April",

            description:
              "Sales decline in April but rebound by 18.6% in May and continue upward in June.",

            impact: "high",
          },

          {
            title: "Average order value stays relatively stable",

            description:
              "Average order value remains close to the same range even while total sales and order counts change.",

            impact: "medium",
          },
        ],

        trends: [
          {
            title: "Positive overall monthly trend",

            description:
              "Sales increase from $85K in January to $124K in June.",

            direction: "up",
          },

          {
            title: "Order volume rises over time",

            description:
              "Monthly order count grows from 105 in January to 158 in June.",

            direction: "up",
          },
        ],

        anomalies: [
          {
            title: "April sales contraction",

            description:
              "April records a 10.2% month-over-month decline, interrupting the otherwise upward pattern.",

            severity: "medium",
          },
        ],

        hypotheses: [
          {
            rank: 1,

            title: "Order volume is the main driver of sales growth",

            description:
              "Sales appear to increase primarily because more orders are being placed while average order value remains relatively stable.",

            confidence: 0.91,

            evidence: [
              "Order count rises from 105 to 158",
              "Average order value stays in a narrow range",
              "Sales rise alongside order volume",
            ],
          },

          {
            rank: 2,

            title: "April may reflect a short-term demand slowdown",

            description:
              "The isolated April decline may have been caused by temporary customer, seasonal, or operational effects rather than a lasting trend.",

            confidence: 0.78,

            evidence: [
              "April is the only negative growth month",
              "May immediately rebounds by 18.6%",
            ],
          },

          {
            rank: 3,

            title: "Recent momentum may continue",

            description:
              "The May and June recovery suggests the business entered the next period with stronger demand momentum.",

            confidence: 0.71,

            evidence: [
              "May growth is strongly positive",
              "June sets the period sales high",
            ],
          },
        ],

        recommendations: [
          {
            title: "Investigate April",

            description:
              "Compare April customer activity, product availability, and order composition with March and May to identify the reason for the temporary drop.",

            priority: "high",
          },

          {
            title: "Prepare capacity for higher order volume",

            description:
              "Because recent sales growth is associated with more orders, ensure operations can support continued transaction growth.",

            priority: "medium",
          },

          {
            title: "Monitor average order value",

            description:
              "Track whether order value begins to decline as volume grows so revenue quality remains healthy.",

            priority: "medium",
          },
        ],

        predictions: [
          {
            title: "Next-period sales direction",

            description:
              "Based on the recent recovery and June peak, the next period is more likely to remain above the January-April average than fall below it.",

            confidence: "medium",
          },
        ],

        businessStory:
          "Monthly sales show healthy overall growth, moving from $85K in January to $124K in June. The main interruption is April, when sales fall by 10.2%, but the decline is short lived: May rebounds sharply and June reaches the period high. Because average order value remains fairly stable while order volume rises, transaction growth appears to be the strongest explanation for improving sales.",
      },
    };
  }

  // =====================================================
  // REVENUE GROWTH
  // =====================================================

  if (goalResult.goalType === "growth_analysis") {
    return {
      success: true,

      data: {
        resultType: "revenue_growth_insights",

        keyInsights: [
          {
            title: "Revenue increased by nearly 60%",

            description:
              "Monthly revenue rises from $76K in January to $121.5K in June, representing 59.9% overall growth.",

            impact: "high",
          },

          {
            title: "Growth remains positive every measured month",

            description:
              "Each month after January records positive month-over-month revenue growth.",

            impact: "high",
          },

          {
            title: "May shows the strongest acceleration",

            description:
              "May records the strongest month-over-month increase at approximately 13%.",

            impact: "medium",
          },
        ],

        trends: [
          {
            title: "Consistent upward revenue trajectory",

            description:
              "Revenue increases sequentially throughout the analyzed period.",

            direction: "up",
          },

          {
            title: "Cumulative revenue compounds steadily",

            description:
              "Cumulative revenue reaches $576.5K by June as each month adds a larger contribution.",

            direction: "up",
          },
        ],

        anomalies: [],

        hypotheses: [
          {
            rank: 1,

            title: "Underlying demand is expanding",

            description:
              "Sustained positive monthly growth may indicate a broad increase in customer demand rather than a one-month spike.",

            confidence: 0.86,

            evidence: [
              "Revenue rises in every month",
              "Growth remains positive throughout the period",
            ],
          },

          {
            rank: 2,

            title: "May may reflect a successful commercial push",

            description:
              "The stronger May acceleration may be associated with promotions, seasonal demand, or a concentration of high-value orders.",

            confidence: 0.72,

            evidence: [
              "May has the strongest monthly growth rate",
              "June maintains the higher revenue base",
            ],
          },

          {
            rank: 3,

            title: "Growth quality appears stable",

            description:
              "Because the revenue curve rises gradually rather than through one extreme jump, the pattern may be more sustainable.",

            confidence: 0.69,

            evidence: [
              "No negative-growth month is present",
              "Revenue increases progressively",
            ],
          },
        ],

        recommendations: [
          {
            title: "Identify the drivers behind May growth",

            description:
              "Break May revenue down by products, customers, categories, and markets to understand what caused the strongest acceleration.",

            priority: "high",
          },

          {
            title: "Protect the higher June revenue base",

            description:
              "Monitor inventory, fulfillment, and customer retention so recent gains are not lost.",

            priority: "high",
          },

          {
            title: "Track growth rate alongside absolute revenue",

            description:
              "Continue monitoring both revenue size and percentage growth to detect early signs of slowing momentum.",

            priority: "medium",
          },
        ],

        predictions: [
          {
            title: "Revenue outlook",

            description:
              "If the current positive sequence continues, near-term revenue is likely to remain above the early-period baseline.",

            confidence: "medium",
          },
        ],

        businessStory:
          "Revenue performance is consistently positive. The business moves from $76K in January to $121.5K in June without recording a negative month-over-month change. May provides the strongest acceleration, while June preserves that higher base. The next analytical priority should be to identify which products, customers, or markets produced the May acceleration and whether those drivers are repeatable.",
      },
    };
  }

  // =====================================================
  // TOP PRODUCTS
  // =====================================================

  if (goalResult.goalType === "ranking_analysis") {
    return {
      success: true,

      data: {
        resultType: "product_ranking_insights",

        keyInsights: [
          {
            title: "Côte de Blaye leads product revenue",

            description:
              "Côte de Blaye generates $62.9K, making it the strongest product in the current top-product analysis.",

            impact: "high",
          },

          {
            title: "Revenue leadership is not the same as volume leadership",

            description:
              "Some products with lower quantities still generate strong revenue because their average unit prices are higher.",

            impact: "high",
          },

          {
            title: "Rössle Sauerkraut has high volume but lower revenue",

            description:
              "The product has the highest quantity among the listed products but ranks lower in revenue because of its lower average unit price.",

            impact: "medium",
          },
        ],

        trends: [
          {
            title: "Premium products dominate revenue ranking",

            description:
              "Higher-priced products occupy several of the leading revenue positions.",

            direction: "up",
          },

          {
            title: "Volume and revenue diverge across products",

            description:
              "Products with the most units sold are not always the products producing the most revenue.",

            direction: "mixed",
          },
        ],

        anomalies: [
          {
            title: "High-volume product underperforms on revenue rank",

            description:
              "Rössle Sauerkraut sells 520 units but remains below several lower-volume products in revenue.",

            severity: "low",
          },
        ],

        hypotheses: [
          {
            rank: 1,

            title: "Premium pricing is a major revenue driver",

            description:
              "The revenue ranking may be strongly influenced by average unit price, allowing premium products to outperform higher-volume alternatives.",

            confidence: 0.89,

            evidence: [
              "Côte de Blaye has the highest average unit price",
              "Côte de Blaye also leads revenue",
            ],
          },

          {
            rank: 2,

            title:
              "High-volume products may support traffic rather than revenue leadership",

            description:
              "Lower-priced, high-volume products may be important for demand and basket creation even when they do not lead total revenue.",

            confidence: 0.77,

            evidence: [
              "Several high-volume products rank below premium products in revenue",
            ],
          },

          {
            rank: 3,

            title: "Product mix can be optimized by balancing price and volume",

            description:
              "A stronger portfolio may come from combining premium revenue leaders with dependable high-volume products.",

            confidence: 0.74,

            evidence: [
              "Revenue and quantity rankings differ",
              "Average prices vary substantially",
            ],
          },
        ],

        recommendations: [
          {
            title: "Protect availability of top revenue products",

            description:
              "Prioritize inventory planning for Côte de Blaye and the other leading revenue contributors.",

            priority: "high",
          },

          {
            title: "Cross-sell premium products with high-volume items",

            description:
              "Use popular high-volume products to create opportunities for higher-value product attachment.",

            priority: "medium",
          },

          {
            title: "Review margin, not revenue alone",

            description:
              "Add product cost and gross-margin analysis before making final assortment or promotion decisions.",

            priority: "medium",
          },
        ],

        predictions: [],

        businessStory:
          "The product ranking shows that revenue is driven by a combination of volume and price, but premium pricing has a particularly strong influence. Côte de Blaye leads revenue despite selling fewer units than several other products. This suggests that product strategy should not focus on unit volume alone. ARIA would next examine margin and cross-selling opportunities to determine which products create the highest overall business value.",
      },
    };
  }

  // =====================================================
  // TOP CUSTOMERS
  // =====================================================

  if (goalResult.goalType === "customer_ranking") {
    return {
      success: true,

      data: {
        resultType: "customer_ranking_insights",

        keyInsights: [
          {
            title: "QUICK-Stop is the highest-value customer",

            description:
              "QUICK-Stop generates $117.4K in sales, the highest total among the customers compared.",

            impact: "high",
          },

          {
            title: "Highest order count does not produce the highest sales",

            description:
              "Save-a-lot Markets has the most orders, but QUICK-Stop leads total sales because its average order value is substantially higher.",

            impact: "high",
          },

          {
            title: "Customer value depends on both frequency and basket size",

            description:
              "The ranking demonstrates that order frequency alone does not fully explain customer contribution.",

            impact: "medium",
          },
        ],

        trends: [
          {
            title: "High-value customers combine frequency with larger orders",

            description:
              "The strongest customers generally maintain both meaningful order counts and strong average order values.",

            direction: "mixed",
          },
        ],

        anomalies: [
          {
            title: "Save-a-lot leads order count but not sales",

            description:
              "Save-a-lot Markets places 31 orders, more than any other listed customer, yet ranks third in total sales.",

            severity: "low",
          },
        ],

        hypotheses: [
          {
            rank: 1,

            title:
              "Average order value explains much of QUICK-Stop's leadership",

            description:
              "QUICK-Stop may lead sales primarily because each order is worth more on average, despite having fewer orders than some competitors.",

            confidence: 0.92,

            evidence: [
              "QUICK-Stop has the highest total sales",
              "Its average order value is the highest among the listed customers",
            ],
          },

          {
            rank: 2,

            title: "Frequency-focused customers may have upsell potential",

            description:
              "Customers with many orders but lower average order values may offer opportunities for larger baskets or premium-product attachment.",

            confidence: 0.82,

            evidence: [
              "Save-a-lot has the highest order count",
              "Its average order value is lower than QUICK-Stop's",
            ],
          },

          {
            rank: 3,

            title: "Customer concentration may create retention risk",

            description:
              "A meaningful share of sales may depend on a relatively small group of high-value accounts.",

            confidence: 0.68,

            evidence: [
              "The leading customers generate substantially more sales than lower-ranked customers",
            ],
          },
        ],

        recommendations: [
          {
            title: "Protect top-customer relationships",

            description:
              "Prioritize retention and service quality for QUICK-Stop, Ernst Handel, and other high-value accounts.",

            priority: "high",
          },

          {
            title: "Upsell high-frequency customers",

            description:
              "Target customers with strong order frequency but lower average order value with bundles or premium-product recommendations.",

            priority: "high",
          },

          {
            title: "Track customer concentration",

            description:
              "Measure the percentage of total sales contributed by the largest customers to manage dependency risk.",

            priority: "medium",
          },
        ],

        predictions: [],

        businessStory:
          "Customer performance is shaped by both how often customers order and how much they spend each time. QUICK-Stop leads sales because its average order value is particularly strong, while Save-a-lot Markets demonstrates that high frequency alone does not guarantee the top revenue position. The immediate opportunity is to protect high-value relationships while increasing basket size among frequent customers.",
      },
    };
  }

  // =====================================================
  // SALES BY CATEGORY
  // =====================================================

  if (goalResult.goalType === "category_composition") {
    return {
      success: true,

      data: {
        resultType: "category_insights",

        keyInsights: [
          {
            title: "Beverages are the largest category",

            description:
              "Beverages generate $142K in sales and also record the highest order volume.",

            impact: "high",
          },

          {
            title: "Meat/Poultry has the highest average order value",

            description:
              "Although Meat/Poultry does not lead total sales, its average order value is higher than the other analyzed categories.",

            impact: "medium",
          },

          {
            title: "Category performance is uneven",

            description:
              "The sales gap between Beverages and Produce indicates that revenue is not evenly distributed across the product portfolio.",

            impact: "medium",
          },
        ],

        trends: [
          {
            title:
              "Higher order volume generally supports higher category sales",

            description:
              "The strongest sales categories also tend to process more orders.",

            direction: "up",
          },
        ],

        anomalies: [
          {
            title: "Meat/Poultry has unusually strong order value",

            description:
              "Meat/Poultry produces the highest average order value despite having fewer orders than the leading categories.",

            severity: "low",
          },
        ],

        hypotheses: [
          {
            rank: 1,

            title: "Beverages lead because of transaction volume",

            description:
              "The category's revenue leadership may be primarily explained by its high number of orders.",

            confidence: 0.9,

            evidence: [
              "Beverages lead total sales",
              "Beverages also lead order count",
            ],
          },

          {
            rank: 2,

            title: "Meat/Poultry may represent a premium basket opportunity",

            description:
              "Its higher average order value suggests customers purchasing from this category may be willing to spend more per transaction.",

            confidence: 0.79,

            evidence: ["Meat/Poultry has the highest average order value"],
          },

          {
            rank: 3,

            title:
              "Lower categories may need volume rather than price improvement",

            description:
              "Categories such as Produce may benefit more from increasing order frequency than from focusing only on transaction value.",

            confidence: 0.7,

            evidence: [
              "Produce has the lowest order count and lowest sales among the compared categories",
            ],
          },
        ],

        recommendations: [
          {
            title: "Protect Beverages availability",

            description:
              "Maintain stock and fulfillment reliability for the category currently generating the most sales and orders.",

            priority: "high",
          },

          {
            title: "Test premium positioning for Meat/Poultry",

            description:
              "Evaluate bundles or premium offers that take advantage of the category's higher average order value.",

            priority: "medium",
          },

          {
            title: "Build demand in lower-volume categories",

            description:
              "Use cross-selling and targeted promotions to increase order frequency in underrepresented categories.",

            priority: "medium",
          },
        ],

        predictions: [],

        businessStory:
          "Category sales are led by Beverages, largely supported by the category's high order volume. Meat/Poultry tells a different story: it generates fewer orders but produces the highest average order value, suggesting stronger basket economics. This creates two different opportunities—protect the high-volume categories that drive scale while developing premium strategies in categories where customers already spend more per transaction.",
      },
    };
  }

  // =====================================================
  // ORDERS BY COUNTRY
  // =====================================================

  if (goalResult.goalType === "country_ranking") {
    return {
      success: true,

      data: {
        resultType: "country_insights",

        keyInsights: [
          {
            title: "USA is the largest market in this comparison",

            description:
              "The USA leads both order count and total sales among the countries analyzed.",

            impact: "high",
          },

          {
            title: "Austria has the highest average order value",

            description:
              "Austria places fewer orders than the largest markets but produces the strongest average order value.",

            impact: "medium",
          },

          {
            title: "Market size and order value vary significantly",

            description:
              "Different countries contribute through different combinations of customer count, order frequency, and average transaction value.",

            impact: "medium",
          },
        ],

        trends: [
          {
            title: "More orders generally correspond with higher country sales",

            description:
              "Countries with larger order counts also tend to generate greater sales totals.",

            direction: "up",
          },
        ],

        anomalies: [
          {
            title: "Austria overperforms on average order value",

            description:
              "Austria records only 42 orders but has the highest average order value in the comparison.",

            severity: "low",
          },
        ],

        hypotheses: [
          {
            rank: 1,

            title: "USA leadership is primarily scale-driven",

            description:
              "The USA may lead sales because it combines the largest customer base with the highest order volume.",

            confidence: 0.91,

            evidence: [
              "USA has the highest order count",
              "USA has the highest total sales",
              "USA has the largest customer count in the mock comparison",
            ],
          },

          {
            rank: 2,

            title: "Austria may contain higher-value customer segments",

            description:
              "Austria's unusually high average order value may indicate a different product mix or more valuable customer profile.",

            confidence: 0.79,

            evidence: [
              "Austria has the highest average order value",
              "Its order count is much lower than the USA",
            ],
          },

          {
            rank: 3,

            title: "Smaller markets may have expansion potential",

            description:
              "Countries with reasonable order value but fewer customers may offer opportunities for customer acquisition.",

            confidence: 0.67,

            evidence: [
              "Several smaller countries maintain solid average order values despite lower order counts",
            ],
          },
        ],

        recommendations: [
          {
            title: "Protect the USA revenue base",

            description:
              "Prioritize retention, availability, and service quality in the largest current market.",

            priority: "high",
          },

          {
            title: "Study Austria's customer and product mix",

            description:
              "Determine why Austria produces a higher average order value and whether the same pattern can be replicated elsewhere.",

            priority: "medium",
          },

          {
            title: "Identify underpenetrated markets",

            description:
              "Compare customer counts and order values to find countries where acquisition could produce attractive returns.",

            priority: "medium",
          },
        ],

        predictions: [],

        businessStory:
          "Country performance is led by the USA because of scale: it has the most orders, customers, and total sales. Austria is notable for a different reason, producing the highest average order value despite much lower volume. The business can therefore pursue two strategies at once—defend the large markets that provide scale and investigate smaller markets where each transaction is unusually valuable.",
      },
    };
  }

  // =====================================================
  // PRICE VS QUANTITY RELATIONSHIP
  // =====================================================

  if (goalResult.goalType === "relationship_analysis") {
    return {
      success: true,

      data: {
        resultType: "relationship_insights",

        keyInsights: [
          {
            title: "Price and quantity show a clear negative relationship",

            description:
              "As product price rises across the sample, quantity sold consistently declines.",

            impact: "high",
          },

          {
            title: "Higher price does not always reduce sales value",

            description:
              "Sales value continues rising through the mid-priced products because increased price offsets part of the volume decline.",

            impact: "high",
          },

          {
            title:
              "The strongest sales value appears in the middle-to-upper price range",

            description:
              "Products around the middle of the price range produce stronger sales value than the cheapest or most expensive examples.",

            impact: "medium",
          },
        ],

        trends: [
          {
            title: "Quantity declines as price increases",

            description:
              "The scatter pattern consistently slopes downward from lower-priced, higher-volume products toward higher-priced, lower-volume products.",

            direction: "down",
          },

          {
            title: "Sales value rises before flattening",

            description:
              "Increasing price initially compensates for lower quantity, but that benefit weakens at the highest prices.",

            direction: "mixed",
          },
        ],

        anomalies: [],

        hypotheses: [
          {
            rank: 1,

            title: "Customer demand is price sensitive",

            description:
              "The consistent inverse relationship suggests customers purchase fewer units as price increases.",

            confidence: 0.94,

            evidence: [
              "Quantity falls steadily as product price increases",
              "The relationship is visible across the full mock sample",
            ],
          },

          {
            rank: 2,

            title: "There may be a revenue-maximizing price zone",

            description:
              "Mid-to-upper-priced products may balance price and demand more effectively than either extreme.",

            confidence: 0.84,

            evidence: [
              "Sales value peaks around the middle-to-upper portion of the price range",
              "Highest-priced products lose enough volume to reduce sales value",
            ],
          },

          {
            rank: 3,

            title: "Premium pricing may require stronger differentiation",

            description:
              "The steep volume decline at higher prices may mean premium products need stronger perceived value to maintain demand.",

            confidence: 0.72,

            evidence: ["High-price products have the lowest quantities"],
          },
        ],

        recommendations: [
          {
            title: "Test the middle price range",

            description:
              "Evaluate margin and conversion around the price range where sales value is strongest before making broad price changes.",

            priority: "high",
          },

          {
            title: "Avoid optimizing for quantity alone",

            description:
              "Use revenue and margin alongside units sold because lower volume can still create stronger commercial value.",

            priority: "high",
          },

          {
            title: "Segment products before changing prices",

            description:
              "Analyze categories, product quality, and customer segments so differences in demand are not incorrectly attributed to price alone.",

            priority: "medium",
          },
        ],

        predictions: [
          {
            title: "Demand response to further price increases",

            description:
              "If the current relationship persists, additional price increases are likely to reduce unit demand unless product value or customer mix changes.",

            confidence: "medium",
          },
        ],

        businessStory:
          "The analysis indicates clear price sensitivity: quantity sold falls as prices rise. However, that does not mean the cheapest products create the most value. Higher prices initially compensate for lower volume, and sales value becomes strongest in the middle-to-upper price range before weakening at the highest prices. This suggests ARIA should evaluate price, volume, revenue, and eventually margin together rather than optimizing any one metric in isolation.",
      },
    };
  }

  // =====================================================
  // NO SPECIALIZED INSIGHT RESULT
  // =====================================================

  return {
    success: true,

    data: {
      resultType: "general_insights",

      keyInsights: [],

      trends: [],

      anomalies: [],

      hypotheses: [],

      recommendations: [],

      predictions: [],

      businessStory:
        "ARIA does not yet have a specialized mock Insight Agent response for this analysis type.",
    },
  };
};

// =========================================================
// FEEDBACK
// =========================================================

export const submitFeedback = async (feedbackData) => {
  console.log("Feedback request prepared:", feedbackData);

  await delay(800);

  if (SIMULATE_FEEDBACK_FAILURE_ONCE && !hasSimulatedFeedbackFailure) {
    hasSimulatedFeedbackFailure = true;

    throw new Error("Feedback submission test failure. Please try again.");
  }

  return {
    success: true,
  };
};

// =========================================================
// API CONFIGURATION
// =========================================================

export { API_BASE_URL };
