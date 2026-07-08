"""Seed the golden evaluation dataset.

Questions are answerable from the ingested Kubernetes corpus (pods,
deployments, services). Each case carries a reference answer, the keywords a
grounded answer should contain, and the source doc it should draw from.
Idempotent: re-seeding replaces the suite's cases.
"""
from sqlmodel import Session, delete, select

from app.db import engine, init_db
from app.models import EvalSuite, TestCase

SUITE_NAME = "k8s-basics"

CASES: list[dict] = [
    {
        "question": "What is a Pod in Kubernetes?",
        "gold_answer": "A Pod is the smallest deployable unit in Kubernetes and wraps one or more containers that share network and storage.",
        "gold_keywords": ["smallest", "deployable", "unit", "containers"],
        "gold_sources": ["pods.md"],
    },
    {
        "question": "Can containers in the same Pod share resources?",
        "gold_answer": "Yes, containers in the same Pod share the same network namespace and can share mounted storage volumes.",
        "gold_keywords": ["network", "share", "volumes"],
        "gold_sources": ["pods.md"],
    },
    {
        "question": "Why should clients reach Pods through a Service?",
        "gold_answer": "Because Pod IP addresses are ephemeral and change when Pods restart, so a Service provides a stable endpoint.",
        "gold_keywords": ["ephemeral", "IP", "stable", "Service"],
        "gold_sources": ["pods.md", "services.md"],
    },
    {
        "question": "What does a Deployment do?",
        "gold_answer": "A Deployment provides declarative updates for Pods and ReplicaSets, changing actual state to match the desired state at a controlled rate.",
        "gold_keywords": ["declarative", "ReplicaSet", "desired state"],
        "gold_sources": ["deployments.md"],
    },
    {
        "question": "How do rolling updates work in a Deployment?",
        "gold_answer": "A Deployment creates a new ReplicaSet and gradually shifts Pods from the old ReplicaSet to the new one, enabling zero-downtime updates.",
        "gold_keywords": ["ReplicaSet", "gradually", "rolling", "downtime"],
        "gold_sources": ["deployments.md"],
    },
    {
        "question": "What controls how many Pods are unavailable during a rolling update?",
        "gold_answer": "The maxUnavailable and maxSurge settings control how many Pods can be down and how many extra Pods can be created during an update.",
        "gold_keywords": ["maxUnavailable", "maxSurge"],
        "gold_sources": ["deployments.md"],
    },
    {
        "question": "How can a Deployment be scaled automatically?",
        "gold_answer": "Through a HorizontalPodAutoscaler, which adjusts the number of replicas based on observed metrics such as CPU utilization.",
        "gold_keywords": ["HorizontalPodAutoscaler", "replicas", "metrics"],
        "gold_sources": ["deployments.md"],
    },
    {
        "question": "What is a Service in Kubernetes?",
        "gold_answer": "A Service is an abstraction that defines a stable network endpoint for a set of Pods and load-balances traffic across them.",
        "gold_keywords": ["stable", "endpoint", "load-balances", "Pods"],
        "gold_sources": ["services.md"],
    },
    {
        "question": "How does a Service select which Pods back it?",
        "gold_answer": "A Service uses label selectors; any Pod whose labels match the selector becomes part of the Service's endpoints.",
        "gold_keywords": ["label", "selector", "endpoints"],
        "gold_sources": ["services.md"],
    },
    {
        "question": "What are the main Service types?",
        "gold_answer": "ClusterIP, NodePort, LoadBalancer, and ExternalName are the Service types.",
        "gold_keywords": ["ClusterIP", "NodePort", "LoadBalancer", "ExternalName"],
        "gold_sources": ["services.md"],
    },
    {
        "question": "How are Services discovered by name?",
        "gold_answer": "Kubernetes runs internal DNS so a Service is resolvable by a name like service.namespace.svc.cluster.local.",
        "gold_keywords": ["DNS", "name", "cluster.local"],
        "gold_sources": ["services.md"],
    },
    {
        "question": "What decides whether a Pod is ready to receive traffic?",
        "gold_answer": "Readiness probes let the kubelet decide whether a Pod is ready to receive traffic; failing Pods are removed from Service rotation.",
        "gold_keywords": ["readiness", "probe", "kubelet"],
        "gold_sources": ["pods.md", "services.md"],
    },
]


def seed_default() -> None:
    init_db()
    with Session(engine) as session:
        suite = session.exec(select(EvalSuite).where(EvalSuite.name == SUITE_NAME)).first()
        if suite is None:
            suite = EvalSuite(name=SUITE_NAME, description="Kubernetes basics golden set")
            session.add(suite)
            session.commit()
            session.refresh(suite)
        else:
            session.exec(delete(TestCase).where(TestCase.suite_id == suite.id))
            session.commit()

        for c in CASES:
            session.add(TestCase(suite_id=suite.id, **c))
        session.commit()
        print(f"Seeded suite '{SUITE_NAME}' with {len(CASES)} test cases.")


if __name__ == "__main__":
    seed_default()
