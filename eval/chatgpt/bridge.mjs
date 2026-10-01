// Trusted local process only. No tokens are returned over stdout.
import { createChatGPT } from './build/sdk.mjs';
import { Entry } from '@napi-rs/keyring';
import { randomBytes, createCipheriv, createDecipheriv } from 'node:crypto';
import { spawn } from 'node:child_process';
import { homedir } from 'node:os';
import { join } from 'node:path';

const entry = new Entry('Mozi Evals ChatGPT', 'credential-encryption-v1');
let key;
function encryptionKey() {
  if (key) return key;
  let saved = entry.getPassword();
  if (saved == null) {
    saved = randomBytes(32).toString('base64');
    entry.setPassword(saved);
  }
  key = Buffer.from(saved, 'base64');
  if (key.length !== 32) throw new Error('Keychain encryption key is invalid.');
  return key;
}
const credentialEncryption = {
  id: 'mozi-macos-keychain-aes256gcm-v1',
  isAvailable() { return process.platform === 'darwin'; },
  encrypt(plaintext) {
    const nonce = randomBytes(12);
    const cipher = createCipheriv('aes-256-gcm', encryptionKey(), nonce);
    const ciphertext = Buffer.concat([cipher.update(plaintext, 'utf8'), cipher.final()]);
    return Buffer.concat([nonce, cipher.getAuthTag(), ciphertext]);
  },
  decrypt(bytes) {
    const data = Buffer.from(bytes);
    const decipher = createDecipheriv('aes-256-gcm', encryptionKey(), data.subarray(0,12));
    decipher.setAuthTag(data.subarray(12,28));
    return Buffer.concat([decipher.update(data.subarray(28)), decipher.final()]).toString('utf8');
  },
};
const chatgpt = createChatGPT({
  appName: 'Mozi Evals', appId: 'mozi-evals', redirectPort: 0, sendHostId: true,
  storageDir: join(homedir(), 'Library', 'Application Support', 'Mozi Evals', 'ChatGPT'),
  credentialEncryption,
  openBrowser(url) {
    console.error('Opening ChatGPT authorization. Complete sign-in and review plan access in your browser.');
    return new Promise((resolve,reject) => {
      const child = spawn('open', [url], {stdio:'ignore'});
      child.on('error', reject);
      child.on('exit', code => code === 0 ? resolve() : reject(new Error('Could not open authorization browser.')));
    });
  },
});
try {
  const command = process.argv[2];
  let result;
  if (command === 'sign-in') {
    const session = await chatgpt.signIn();
    result = {session, models:session.sharing ? await chatgpt.listModels() : []};
  } else if (command === 'models') {
    const session = await chatgpt.getSession();
    if (!session.sharing) throw new Error('Sign in and enable ChatGPT plan usage first.');
    result = {models:await chatgpt.listModels(), sharing:true};
  } else if (command === 'request') {
    let input=''; for await (const chunk of process.stdin) input += chunk;
    const request=JSON.parse(input);
    // Credentials remain inside the DevKit's authenticated request boundary.
    result = await chatgpt.streamResponse({...request, signal:AbortSignal.timeout(180_000)});
  } else throw new Error('Use sign-in, models, or request.');
  console.log(JSON.stringify(result));
} catch (error) {
  console.error(JSON.stringify(error.toJSON?.() ?? {error: error.code ?? 'local_connection_error', message:error.message}));
  process.exitCode=1;
}
