// Report IDs support idempotent retries; they are not authentication credentials.
export function createReportId(cryptoProvider=globalThis.crypto) {
  if(typeof cryptoProvider?.randomUUID==='function')return cryptoProvider.randomUUID();
  // getRandomValues also works on HTTP origins where randomUUID may be unavailable.
  if(typeof cryptoProvider?.getRandomValues!=='function') {
    throw new Error('This browser cannot generate a report ID. Please use a browser with Web Crypto support. Your entries have been kept.');
  }
  const bytes=cryptoProvider.getRandomValues(new Uint8Array(16));
  bytes[6]=(bytes[6]&0x0f)|0x40;
  bytes[8]=(bytes[8]&0x3f)|0x80;
  const hex=Array.from(bytes,byte=>byte.toString(16).padStart(2,'0')).join('');
  return `${hex.slice(0,8)}-${hex.slice(8,12)}-${hex.slice(12,16)}-${hex.slice(16,20)}-${hex.slice(20)}`;
}
