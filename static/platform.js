const requestPanel = document.getElementById('platform-request');
if (requestPanel) {
  setInterval(async () => {
    if (document.hidden) return;
    try {
      const response = await fetch(requestPanel.dataset.url, {credentials: 'same-origin', cache: 'no-store'});
      if (!response.ok) return;
      const item = await response.json();
      if (`${item.status}:${item.step}` !== requestPanel.dataset.state) location.reload();
    } catch (_) { /* State remains available during a local network interruption. */ }
  }, 5000);
}
