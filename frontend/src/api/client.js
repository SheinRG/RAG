import axios from 'axios';
import { supabase } from '../lib/supabase';

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

const api = axios.create({
  baseURL: `${API_URL}/api`,
  headers: { 'Content-Type': 'application/json' },
});

/**
 * Return a valid access token, refreshing the Supabase session if the cached
 * one has expired. Concurrent callers share a single in-flight refresh so a
 * burst of parallel 401s cannot trigger a burst of refresh requests.
 */
let refreshInFlight = null;

async function getFreshToken() {
  if (!refreshInFlight) {
    refreshInFlight = supabase.auth
      .getSession()
      .then(({ data }) => data?.session?.access_token ?? null)
      .catch(() => null)
      .finally(() => {
        refreshInFlight = null;
      });
  }
  return refreshInFlight;
}

function clearSession() {
  localStorage.removeItem('access_token');
  localStorage.removeItem('user');
}

// Inject auth token on every request
api.interceptors.request.use((config) => {
  const token = localStorage.getItem('access_token');
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// Handle 401s globally.
// A 401 usually means the cached access token aged out, not that the user is
// really signed out — the Supabase SDK still holds a valid refresh token. Ask
// it for a fresh session and replay the request once before giving up, so a
// long research session is not interrupted by a forced logout.
api.interceptors.response.use(
  (response) => response,
  async (error) => {
    const original = error.config;

    if (error.response?.status === 401 && original && !original._retriedAfterRefresh) {
      original._retriedAfterRefresh = true;
      const token = await getFreshToken();
      if (token) {
        localStorage.setItem('access_token', token);
        original.headers = { ...original.headers, Authorization: `Bearer ${token}` };
        return api(original);
      }
    }

    if (error.response?.status === 401) {
      clearSession();
      window.location.href = '/login';
    }

    return Promise.reject(error);
  }
);

export default api;

/**
 * Stream a POST request and return a ReadableStream of SSE events.
 * Retries once with a refreshed token if the session had expired.
 */
export async function streamPost(path, body, signal) {
  const send = async (token) =>
    fetch(`${API_URL}/api${path}`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify(body),
      signal,
    });

  let response = await send(localStorage.getItem('access_token'));

  if (response.status === 401) {
    const token = await getFreshToken();
    if (token) {
      localStorage.setItem('access_token', token);
      response = await send(token);
    }
  }

  if (!response.ok) {
    if (response.status === 401) {
      clearSession();
      throw new Error('Your session has expired. Please sign in again.');
    }
    // The body may hold internal detail; surface only the status to the UI and
    // keep the full text in the console for debugging.
    const errorText = await response.text().catch(() => '');
    console.error(`Stream request failed: ${response.status}`, errorText);
    throw new Error(`Request failed (${response.status}). Please try again.`);
  }

  return response.body;
}
