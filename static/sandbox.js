const sandboxRun = document.getElementById('sandbox-run');
if (sandboxRun && ['queued', 'running'].includes(sandboxRun.dataset.status)) {
  const poll = async () => {
    if (document.hidden) return;
    try {
      const response = await fetch(sandboxRun.dataset.statusUrl, {credentials: 'same-origin', cache: 'no-store'});
      if (!response.ok) return;
      const run = await response.json();
      if (!run.active || run.status !== sandboxRun.dataset.status) window.location.reload();
    } catch (_) { /* Keep the page usable while the local server is unavailable. */ }
  };
  setInterval(poll, 5000);
}
