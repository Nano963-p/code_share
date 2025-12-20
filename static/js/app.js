async function postJSON(url) {
  const res = await fetch(url, { method: "POST", headers: { "X-Requested-With": "fetch" } });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || "Request failed");
  return data;
}

function toast(msg) {
  // Simple client-side toast (optional)
  const stack = document.querySelector(".toast-stack") || null;
  if (!stack) return;
  const el = document.createElement("div");
  el.className = "toast info";
  el.textContent = msg;
  stack.prepend(el);
  setTimeout(() => el.remove(), 3500);
}

document.addEventListener("click", async (e) => {
  const starBtn = e.target.closest("[data-star-btn]");
  if (starBtn) {
    const pid = starBtn.getAttribute("data-project-id");
    try {
      const data = await postJSON(`/api/projects/${pid}/star`);
      const text = starBtn.querySelector("[data-star-text]");
      const count = starBtn.querySelector("[data-stars-count]");
      if (text) text.textContent = data.starred ? "Starred" : "Star";
      if (count) count.textContent = `(${data.stars_count})`;
      toast(data.starred ? "Project starred" : "Star removed");
    } catch (err) {
      alert(err.message);
    }
  }

  const followBtn = e.target.closest("[data-follow-btn]");
  if (followBtn) {
    const uid = followBtn.getAttribute("data-user-id");
    try {
      const data = await postJSON(`/api/users/${uid}/follow`);
      const text = followBtn.querySelector("[data-follow-text]");
      if (text) text.textContent = data.following ? "Following" : "Follow";
      toast(data.following ? "Following user" : "Unfollowed user");
    } catch (err) {
      alert(err.message);
    }
  }
});
