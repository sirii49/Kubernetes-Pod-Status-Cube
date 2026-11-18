# Kubernetes Pod Status Cube

A software-only Flask dashboard that reads real Pod, Deployment, Namespace and Event data from a local Kubernetes cluster (Minikube) using the Kubernetes Python client.

## Requirements

- Windows 10/11
- Python 3.10+
- Minikube
- kubectl
- A Minikube driver (Docker Desktop is one option; other supported drivers are possible)

No cloud account or paid API is required. The application and cluster run locally. Internet access may be needed initially to install Python packages and pull container images.

## 1. Start Minikube

Open PowerShell:

```powershell
minikube start
kubectl cluster-info
kubectl get nodes
```

If you use Docker as the Minikube driver, make sure Docker Desktop is running before `minikube start`.

## 2. Create sample workloads

From the project root:

```powershell
kubectl apply -f .\kubernetes\namespace.yaml
kubectl apply -f .\kubernetes\sample-app.yaml
kubectl get pods -n pod-cube-demo -w
```

Wait until the demo-web Pods show Running and Ready.

## 3. Install and run the application

From the project root:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
py -m pip install -r requirements.txt
py backend\app.py
```

If PowerShell blocks virtual-environment activation, either use `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` for that terminal session, or skip activation and run `.venv\Scripts\python.exe -m pip install -r requirements.txt` followed by `.venv\Scripts\python.exe backend\app.py`.

Open:

http://127.0.0.1:5000

The backend uses the current kubeconfig, which Minikube normally updates automatically. Check `kubectl get pods -A` in the same Windows user account if the dashboard cannot connect.

## 4. Test the red state (optional)

This manifest creates a Pod with an intentionally invalid image to demonstrate ImagePullBackOff:

```powershell
kubectl apply -f .\kubernetes\crash-demo.yaml
kubectl get pods -n pod-cube-demo -w
```

After the Pod reports ImagePullBackOff, refresh the dashboard. It should be classified RED.

Remove the test workload afterward:

```powershell
kubectl delete -f .\kubernetes\crash-demo.yaml
```

## 5. Test updating

Change the sample deployment image tag to another valid Nginx tag in `kubernetes/sample-app.yaml`, then apply it:

```powershell
kubectl apply -f .\kubernetes\sample-app.yaml
kubectl rollout status deployment/demo-web -n pod-cube-demo
```

A rollout can be brief. The dashboard polls every five seconds, so a very fast update may finish between polls. For a visible demonstration, temporarily scale the deployment or use a slower image pull in a test environment.

## 6. Stop and clean up

```powershell
kubectl delete namespace pod-cube-demo
minikube stop
```

## Status classification notes

- RED: Failed Pod or container waiting reasons such as CrashLoopBackOff, ImagePullBackOff and ErrImagePull.
- YELLOW: Pods matched to a Deployment whose updated/available replica counts indicate an ongoing rollout.
- GREEN: Pod phase is Running and all reported regular containers are ready.
- GREY: Pending, unknown, or Running but not fully ready.
- BLUE: Succeeded/completed Pod.

Kubernetes Pod phase alone is not enough to identify every container failure; the backend also inspects container waiting and terminated reasons. The rollout detector is intentionally a practical dashboard heuristic, not a replacement for Kubernetes' full rollout controller logic.

## API routes

- `GET /api/cluster`
- `GET /api/pods`
- `GET /api/pods/<namespace>/<pod_name>`
- `GET /api/deployments`
- `GET /api/namespaces`
- `GET /api/events`
- `GET /api/alerts`
- `GET /api/history`
- `POST /api/monitor`
- `POST /api/alerts/acknowledge`

## Notes

- SQLite is created automatically at `database/monitoring.db`.
- The dashboard refreshes every five seconds and records snapshots after successful cluster reads.
- This starter application is intended for local development and demonstration. Do not expose the Flask development server directly to the public internet.
- Kubernetes access is inherited from your local kubeconfig. Keep that file private.


## Public demo deployment (simulated Kubernetes)

For a public demonstration, set `DEMO_MODE=true`. In this mode the dashboard returns clearly labelled sample pod, deployment and event data. It does not connect to a live Kubernetes cluster.

### Deploy on Render

1. Push this project folder to a GitHub repository (do not upload `.venv` or database files).
2. In Render, choose **New + → Blueprint** and connect the repository.
3. Render detects `render.yaml`; create the web service.
4. After deployment, open the generated `https://...onrender.com` URL.
5. The dashboard should show **Demo mode · simulated data**.

The free service may sleep when idle and take a short time to wake up. Its local SQLite history may reset when the service restarts or is redeployed. For persistent history, configure a persistent disk or external database.

This public demo uses simulated sample data, not live cluster monitoring. Keep `DEMO_MODE=true` for the public demo unless you have separately configured secure access to a real Kubernetes cluster.
