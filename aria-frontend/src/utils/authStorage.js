// =========================================================
// ARIA FRONTEND AUTH STORAGE
// =========================================================
//
// FRONTEND DEVELOPMENT VERSION
//
// Current:
// - Accounts are stored in localStorage.
// - Passwords are not stored as plain text.
// - Passwords are hashed using PBKDF2 + SHA-256.
//
// Later:
// React
//   ↓
// FastAPI
//   ↓
// PostgreSQL
// =========================================================

const USERS_STORAGE_KEY = "aria_registered_users";

// =========================================================
// GET USERS
// =========================================================

const getStoredUsers = () => {
  try {
    const storedUsers = localStorage.getItem(USERS_STORAGE_KEY);

    if (!storedUsers) {
      return [];
    }

    const parsedUsers = JSON.parse(storedUsers);

    return Array.isArray(parsedUsers) ? parsedUsers : [];
  } catch (error) {
    console.error("Could not read ARIA users:", error);

    return [];
  }
};

// =========================================================
// SAVE USERS
// =========================================================

const saveStoredUsers = (users) => {
  localStorage.setItem(USERS_STORAGE_KEY, JSON.stringify(users));
};

// =========================================================
// NORMALIZE EMAIL
// =========================================================

const normalizeEmail = (email) => {
  return email.trim().toLowerCase();
};

// =========================================================
// RANDOM SALT
// =========================================================

const createSalt = () => {
  const saltBytes = crypto.getRandomValues(new Uint8Array(16));

  return Array.from(saltBytes)
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");
};

// =========================================================
// BUFFER TO HEX
// =========================================================

const bufferToHex = (buffer) => {
  return Array.from(new Uint8Array(buffer))
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");
};

// =========================================================
// HASH PASSWORD
// =========================================================

const hashPassword = async (password, salt) => {
  const encoder = new TextEncoder();

  const passwordKey = await crypto.subtle.importKey(
    "raw",
    encoder.encode(password),
    {
      name: "PBKDF2",
    },
    false,
    ["deriveBits"],
  );

  const derivedBits = await crypto.subtle.deriveBits(
    {
      name: "PBKDF2",

      salt: encoder.encode(salt),

      iterations: 100000,

      hash: "SHA-256",
    },

    passwordKey,

    256,
  );

  return bufferToHex(derivedBits);
};

// =========================================================
// REGISTER USER
// =========================================================

export const registerLocalUser = async (email, password) => {
  const normalizedEmail = normalizeEmail(email);

  const users = getStoredUsers();

  const existingUser = users.find((user) => user.email === normalizedEmail);

  if (existingUser) {
    return {
      success: false,

      message: "An account with this email already exists.",
    };
  }

  const salt = createSalt();

  const passwordHash = await hashPassword(password, salt);

  const newUser = {
    id: `aria-user-${Date.now()}`,

    email: normalizedEmail,

    passwordHash,

    salt,

    createdAt: new Date().toISOString(),
  };

  users.push(newUser);

  saveStoredUsers(users);

  return {
    success: true,

    user: {
      id: newUser.id,

      email: newUser.email,
    },
  };
};

// =========================================================
// LOGIN USER
// =========================================================

export const authenticateLocalUser = async (email, password) => {
  const normalizedEmail = normalizeEmail(email);

  const users = getStoredUsers();

  const user = users.find((storedUser) => storedUser.email === normalizedEmail);

  if (!user) {
    return {
      success: false,

      code: "USER_NOT_FOUND",

      message:
        "No account exists with this email. Please create an account first.",
    };
  }
  const enteredPasswordHash = await hashPassword(password, user.salt);

  if (enteredPasswordHash !== user.passwordHash) {
    return {
      success: false,

      message: "Incorrect password. Please try again.",
    };
  }

  return {
    success: true,

    user: {
      id: user.id,

      email: user.email,
    },
  };
};
