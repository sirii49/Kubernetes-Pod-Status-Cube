let currentPods = [];
let chart = null;
const $ = (id) => document.getElementById(id);
const pageNames = {overview:"Overview",pods:"Pod monitoring",deployments:"Deployments",events:"Cluster events",alerts:"Alerts",history:"Monitoring history"};

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
}
function tag(p) {
  const color = p.color === "GREEN" ? "green" : p.color === "RED" ? "red" : p.color === "YELLOW" ? "yellow" : p.color === "BLUE" ? "blue" : "grey";
  return `<span class="status-tag ${color}"><i class="led ${color}"></i>${escapeHtml(p.display_state || p.status)}</span>`;
}
function showPage(name) {
  document.querySelectorAll(".page").forEach(p => p.classList.add("hidden"));
  $("page-" + name).classList.remove("hidden");
  document.querySelectorAll(".nav-item").forEach(b => b.classList.toggle("active", b.dataset.page === name));
  $("page-title").textContent = pageNames[name];
  if (name === "events") loadEvents();
  if (name === "alerts") loadAlerts();
  if (name === "history") loadHistory();
}
document.querySelectorAll(".nav-item").forEach(b => b.addEventListener("click", () => showPage(b.dataset.page)));
document.querySelectorAll("[data-goto]").forEach(b => b.addEventListener("click", () => showPage(b.dataset.goto)));

async function api(url, options) {
  const response = await fetch(url, options);
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || data.hint || "Request failed");
  return data;
}
function renderRows(pods, target, compact=false) {
  if (!pods.length) { target.innerHTML = `<tr><td colspan="${compact?5:8}" class="empty">No Pods found for this filter.</td></tr>`; return; }
  target.innerHTML = pods.map(p => compact
    ? `<tr><td><button class="pod-link" data-pod="${escapeHtml(p.name)}" data-ns="${escapeHtml(p.namespace)}">${escapeHtml(p.name)}</button></td><td>${escapeHtml(p.namespace)}</td><td>${escapeHtml(p.status)}</td><td>${tag(p)}</td><td>${p.restarts}</td></tr>`
    : `<tr><td><button class="pod-link" data-pod="${escapeHtml(p.name)}" data-ns="${escapeHtml(p.namespace)}">${escapeHtml(p.name)}</button></td><td>${escapeHtml(p.namespace)}</td><td>${escapeHtml(p.status)}</td><td>${tag(p)}</td><td>${p.ready}/${p.container_total}</td><td>${p.restarts}</td><td>${escapeHtml(p.node)}</td><td>${escapeHtml(p.ip)}</td></tr>`
  ).join("");
  target.querySelectorAll("[data-pod]").forEach(b => b.addEventListener("click", () => loadPodDetail(b.dataset.ns,b.dataset.pod)));
}
function updateChart(counts) {
  const ctx = $("statusChart");
  const values = [counts.running, counts.crashed, counts.updating, counts.other];
  if (!chart) chart = new Chart(ctx,{type:"doughnut",data:{labels:["Running","Crash","Updating","Other"],datasets:[{data:values,backgroundColor:["#35d39a","#ff6376","#f6c85f","#59677e"],borderWidth:0,hoverOffset:5}]},options:{responsive:true,maintainAspectRatio:false,cutout:"72%",plugins:{legend:{position:"bottom",labels:{color:"#9eabc0",usePointStyle:true,boxWidth:7,padding:14,font:{size:10}}}}}});
  else { chart.data.datasets[0].data=values; chart.update(); }
}
async function refresh() {
  try {
    const data = await api("/api/cluster");
    currentPods = data.pods || [];
    $("connection").className = "connection connected"; $("connection").innerHTML = "<i></i> " + (data.demo_mode ? "Demo mode · simulated data" : "Cluster connected");
    $("connection-warning").classList.add("hidden");
    $("total-pods").textContent = data.pod_count;
    $("running-pods").textContent = data.running;
    $("crashed-pods").textContent = data.crashed;
    $("updating-pods").textContent = data.updating;
    $("legend-running").textContent = data.running;
    $("legend-crash").textContent = data.crashed;
    $("legend-updating").textContent = data.updating;
    const other = currentPods.length-data.running-data.crashed-data.updating;
    const cube = $("main-cube");
    const dominant = data.crashed ? "red" : data.updating ? "yellow" : data.running ? "green" : "";
    cube.className = "cube " + dominant;
    $("cube-label").textContent = data.crashed ? "ATTENTION" : data.updating ? "UPDATING" : data.running ? "RUNNING" : "NO PODS";
    updateChart({running:data.running,crashed:data.crashed,updating:data.updating,other:Math.max(0,other)});
    renderRows(currentPods.slice(0,7),$("overview-pods"),true);
    applyPodFilters();
    renderDeployments(data.deployments || []);
    await api("/api/monitor",{method:"POST"});
    $("last-refresh").textContent = "Last updated " + new Date(data.refreshed_at).toLocaleTimeString();
    await loadNamespaces();
  } catch (err) {
    $("connection").className = "connection disconnected"; $("connection").innerHTML = "<i></i> Disconnected";
    $("connection-warning").classList.remove("hidden"); $("connection-error").textContent = err.message;
    ["total-pods","running-pods","crashed-pods","updating-pods"].forEach(id => $(id).textContent="—");
  }
}
function applyPodFilters() {
  const ns = $("namespace-filter").value, status = $("status-filter").value, search = $("pod-search").value.toLowerCase();
  const filtered = currentPods.filter(p => (!ns || p.namespace===ns) && (!status || p.display_state===status) && p.name.toLowerCase().includes(search));
  renderRows(filtered,$("pods-table"));
}
async function loadNamespaces() {
  try {
    const list = await api("/api/namespaces"), select = $("namespace-filter"), previous=select.value;
    const options = ['<option value="">All namespaces</option>',...list.map(n=>`<option value="${escapeHtml(n)}">${escapeHtml(n)}</option>`)].join("");
    if (select.dataset.loaded !== "yes") { select.innerHTML=options; select.dataset.loaded="yes"; }
    else if (select.options.length !== list.length+1) select.innerHTML=options;
    select.value = previous;
  } catch (_) {}
}
function renderDeployments(items) {
  $("deployments-table").innerHTML = items.length ? items.map(d=>`<tr><td>${escapeHtml(d.name)}</td><td>${escapeHtml(d.namespace)}</td><td>${d.desired}</td><td>${d.updated}</td><td>${d.ready}</td><td>${d.available}</td><td>${d.rollout==="Complete"?'<span class="status-tag green">Complete</span>':'<span class="status-tag yellow">In progress</span>'}</td></tr>`).join("") : '<tr><td colspan="7" class="empty">No deployments found.</td></tr>';
}
async function loadPodDetail(ns,name) {
  try {
    const p = await api(`/api/pods/${encodeURIComponent(ns)}/${encodeURIComponent(name)}`);
    $("pod-detail").classList.remove("hidden"); $("detail-title").textContent=p.name; $("detail-subtitle").textContent=`Namespace: ${p.namespace} · ${p.detail}`;
    const items=[["Phase",p.status],["Status",p.display_state],["Ready containers",`${p.ready}/${p.container_total}`],["Restarts",p.restarts],["Pod IP",p.ip],["Node",p.node],["Created",p.created?new Date(p.created).toLocaleString():"—"]];
    $("detail-content").innerHTML=`<div class="detail-grid">${items.map(x=>`<div class="detail-item"><small>${escapeHtml(x[0])}</small><b>${escapeHtml(x[1])}</b></div>`).join("")}</div><h4>Containers</h4><div class="table-wrap"><table><thead><tr><th>NAME</th><th>READY</th><th>RESTARTS</th><th>STATE</th></tr></thead><tbody>${p.containers.map(c=>`<tr><td>${escapeHtml(c.name)}</td><td>${c.ready?"Yes":"No"}</td><td>${c.restart_count}</td><td>${escapeHtml(c.state)}</td></tr>`).join("")||'<tr><td colspan="4">No container status reported.</td></tr>'}</tbody></table></div><h4>Conditions</h4>${p.conditions.map(c=>`<p class="muted-line">${escapeHtml(c.type)}: ${escapeHtml(c.status)} — ${escapeHtml(c.message)}</p>`).join("")}`;
    $("pod-detail").scrollIntoView({behavior:"smooth",block:"nearest"});
  } catch(e) { alert("Could not load Pod details: "+e.message); }
}
async function loadEvents() {
  try {
    const items=await api("/api/events");
    $("events-table").innerHTML=items.length?items.map(e=>`<tr><td>${escapeHtml(e.type)}</td><td>${escapeHtml(e.reason)}</td><td>${escapeHtml(e.object)}</td><td>${escapeHtml(e.namespace)}</td><td>${escapeHtml(e.message)}</td><td>${e.time?new Date(e.time).toLocaleString():"—"}</td></tr>`).join(""):'<tr><td colspan="6" class="empty">No events found.</td></tr>';
  } catch(e) {$("events-table").innerHTML=`<tr><td colspan="6" class="empty">${escapeHtml(e.message)}</td></tr>`;}
}
async function loadAlerts() {
  try {
    const items=await api("/api/alerts");
    $("alerts-list").innerHTML=items.length?items.map(a=>`<div class="alert-item"><div><strong>${a.active?"ACTIVE":"RESOLVED"} · ${escapeHtml(a.pod_name)}</strong><p>${escapeHtml(a.message)} · Namespace: ${escapeHtml(a.namespace)}</p><small>First seen: ${new Date(a.first_seen).toLocaleString()} · Last seen: ${new Date(a.last_seen).toLocaleString()}</small></div></div>`).join(""):'<div class="empty">No alerts recorded.</div>';
  } catch(e) {$("alerts-list").textContent=e.message;}
}
async function loadHistory() {
  try {
    const items=await api("/api/history?limit=150");
    $("history-table").innerHTML=items.length?items.map(h=>`<tr><td>${escapeHtml(h.pod_name)}</td><td>${escapeHtml(h.namespace)}</td><td>${escapeHtml(h.state)}</td><td>${h.restarts}</td><td>${new Date(h.recorded_at).toLocaleString()}</td></tr>`).join(""):'<tr><td colspan="5" class="empty">History will appear after the first successful monitoring refresh.</td></tr>';
  } catch(e) {$("history-table").innerHTML=`<tr><td colspan="5">${escapeHtml(e.message)}</td></tr>`;}
}
$("namespace-filter").addEventListener("change",applyPodFilters);
$("status-filter").addEventListener("change",applyPodFilters);
$("pod-search").addEventListener("input",applyPodFilters);
$("refresh-btn").addEventListener("click",refresh);
$("close-detail").addEventListener("click",()=>$("pod-detail").classList.add("hidden"));
$("ack-alerts").addEventListener("click",async()=>{try{await api("/api/alerts/acknowledge",{method:"POST"});loadAlerts();}catch(e){alert(e.message);}});
refresh();
setInterval(refresh,5000);
