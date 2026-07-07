# Pods

A Pod is the smallest deployable unit in Kubernetes. It represents a single instance of a running process in a cluster and wraps one or more containers that share the same network namespace and storage. Containers in the same Pod can reach each other over localhost and can share mounted volumes.

Most Pods run a single application container. Additional containers, often called sidecars, are added when a helper process needs to run alongside the main application, for example a log shipper or a proxy. All containers in a Pod are always scheduled together onto the same node and share the Pod's lifecycle.

Every Pod is assigned a unique IP address inside the cluster network. Because Pods are ephemeral, this IP is not stable across restarts. When a Pod is deleted and recreated, it typically receives a new IP, which is why clients should reach Pods through a Service rather than by their Pod IP directly.

Pods have a defined lifecycle with phases such as Pending, Running, Succeeded, and Failed. The kubelet on each node reports Pod status back to the control plane. Liveness and readiness probes let the kubelet decide whether to restart a container or whether a Pod is ready to receive traffic.

Pods are rarely created directly in production. Instead they are managed by higher-level controllers such as Deployments, StatefulSets, and DaemonSets, which handle scheduling, scaling, and self-healing so that the desired number of Pods is maintained even when nodes fail.
