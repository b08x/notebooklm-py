import base64
import os

from openinference.instrumentation.dspy import DSPyInstrumentor
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor


def setup_otel():
    os.environ["LANGFUSE_PUBLIC_KEY"] = "pk-lf-123"
    os.environ["LANGFUSE_SECRET_KEY"] = "sk-lf-123"
    os.environ["LANGFUSE_HOST"] = "http://localhost:3000"

    endpoint = (
        os.environ.get("LANGFUSE_HOST", "https://cloud.langfuse.com") + "/api/public/otel/v1/traces"
    )
    auth = base64.b64encode(
        f"{os.environ['LANGFUSE_PUBLIC_KEY']}:{os.environ['LANGFUSE_SECRET_KEY']}".encode()
    ).decode()

    trace.set_tracer_provider(TracerProvider())
    trace.get_tracer_provider().add_span_processor(
        BatchSpanProcessor(
            OTLPSpanExporter(endpoint=endpoint, headers={"Authorization": f"Basic {auth}"})
        )
    )
    DSPyInstrumentor().instrument()
    print("OTEL setup done")


setup_otel()
