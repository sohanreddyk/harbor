# Services

A Service is an abstraction that defines a stable network endpoint for a set of Pods. Because Pods are ephemeral and their IP addresses change, a Service gives clients a consistent address and load-balances traffic across the healthy Pods that back it.

Services select their backing Pods using label selectors. Any Pod whose labels match the selector is added to the Service's set of endpoints, and Pods that fail their readiness probe are automatically removed from rotation so they stop receiving traffic.

There are several Service types. ClusterIP, the default, exposes the Service on an internal cluster IP reachable only from within the cluster. NodePort exposes the Service on a static port on every node. LoadBalancer provisions an external load balancer through the cloud provider. ExternalName maps the Service to a DNS name.

Kubernetes runs an internal DNS service so that Services can be reached by name. A Service named payments in the shop namespace is resolvable at payments.shop.svc.cluster.local, which means applications can discover each other without hardcoding IP addresses.

For HTTP routing that spans multiple Services, an Ingress or Gateway API resource sits in front of Services and routes requests based on host and path. The Service still handles the final load balancing to individual Pods, while the Ingress handles external entry, TLS termination, and virtual hosting.
