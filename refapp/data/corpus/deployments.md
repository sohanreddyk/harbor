# Deployments

A Deployment provides declarative updates for Pods and ReplicaSets. You describe the desired state — which container image to run and how many replicas you want — and the Deployment controller changes the actual state to match it at a controlled rate.

Under the hood a Deployment manages ReplicaSets. Each time you change the Pod template, for example by updating the container image, the Deployment creates a new ReplicaSet and gradually shifts Pods from the old ReplicaSet to the new one. This is how rolling updates work, and it lets you ship a new version with no downtime.

Rolling updates are governed by the maxUnavailable and maxSurge settings. maxUnavailable controls how many Pods can be down during the update, while maxSurge controls how many extra Pods can be created above the desired count. Tuning these values trades update speed against capacity headroom.

If a new version is unhealthy, a Deployment can be rolled back to a previous revision. Kubernetes keeps a bounded history of ReplicaSets so that rollbacks are fast and do not require rebuilding the old configuration by hand.

Scaling a Deployment is done by changing the replica count, either manually or automatically through a HorizontalPodAutoscaler. The autoscaler adjusts the number of replicas based on observed metrics such as CPU utilization or custom application metrics, allowing the workload to grow and shrink with demand.
