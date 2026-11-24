const tracker = document.getElementById('tracker-poll');
if (tracker) {
  const timer = setInterval(async () => {
    try {
      const response = await fetch(tracker.dataset.url, {credentials: 'same-origin', headers: {'Accept': 'application/json'}, cache:'no-store'});
      if (!response.ok || response.redirected) { clearInterval(timer); return; }
      const data = await response.json();
      if (data.status !== tracker.dataset.status || data.events.length !== Number(tracker.dataset.events)) { clearInterval(timer); window.location.reload(); }
    } catch (_) { /* Keep the page usable during a network interruption. */ }
  }, 5000);
}
