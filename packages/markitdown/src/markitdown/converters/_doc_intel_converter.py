import sys
import re

from typing import BinaryIO, Any, List, Optional

from ._html_converter import HtmlConverter
from .._base_converter import DocumentConverter, DocumentConverterResult
from .._stream_info import StreamInfo
from .._exceptions import MissingDependencyException, MISSING_DEPENDENCY_MESSAGE

from azure.core.credentials import AzureKeyCredential

# Try loading optional (but in this case, required) dependencies
# Save reporting of any exceptions for later
_dependency_exc_info = None
try:
    from azure.ai.documentintelligence import DocumentIntelligenceClient
    from azure.ai.documentintelligence.models import (
        AnalyzeDocumentRequest,
        AnalyzeResult,
        DocumentAnalysisFeature,
    )
    from azure.identity import DefaultAzureCredential
except ImportError:
    # Preserve the error and stack trace for later
    _dependency_exc_info = sys.exc_info()


# TODO: currently, there is a bug in the document intelligence SDK with importing the "ContentFormat" enum.
# This constant is a temporary fix until the bug is resolved.
CONTENT_FORMAT = "markdown"


OFFICE_MIME_TYPE_PREFIXES = [
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.openxmlformats-officedocument.presentationml",
    "application/xhtml",
    "text/html",
]

OTHER_MIME_TYPE_PREFIXES = [
    "application/pdf",
    "application/x-pdf",
    "text/html",
    "image/",
]

OFFICE_FILE_EXTENSIONS = [
    ".docx",
    ".xlsx",
    ".pptx",
    ".html",
    ".htm",
]

OTHER_FILE_EXTENSIONS = [
    ".pdf",
    ".jpeg",
    ".jpg",
    ".png",
    ".bmp",
    ".tiff",
    ".heif",
]


class DocumentIntelligenceConverter(DocumentConverter):
    """Specialized DocumentConverter that uses Document Intelligence to extract text from documents."""

    def __init__(
        self,
        *,
        endpoint: str,
        api_key: Optional[str] = None,
        api_version: str = "2024-07-31-preview",
    ):
        super().__init__()

        # Raise an error if the dependencies are not available.
        # This is different than other converters since this one isn't even instantiated
        # unless explicitly requested.
        if _dependency_exc_info is not None:
            raise MissingDependencyException(
                "DocumentIntelligenceConverter requires the optional dependency [az-doc-intel] (or [all]) to be installed. E.g., `pip install markitdown[az-doc-intel]`"
            ) from _dependency_exc_info[
                1
            ].with_traceback(  # type: ignore[union-attr]
                _dependency_exc_info[2]
            )

        self.endpoint = endpoint
        self.api_version = api_version
        
        # use api_key if provided, otherwise use DefaultAzureCredential
        if api_key:
            self.doc_intel_client = DocumentIntelligenceClient(
                endpoint=self.endpoint,
                api_version=self.api_version,
                credential=AzureKeyCredential(api_key),
            )
        else:
            self.doc_intel_client = DocumentIntelligenceClient(
                endpoint=self.endpoint,
                api_version=self.api_version,
                credential=DefaultAzureCredential(),
            )

    def accepts(
        self,
        file_stream: BinaryIO,
        stream_info: StreamInfo,
        **kwargs: Any,  # Options to pass to the converter
    ) -> bool:
        mimetype = (stream_info.mimetype or "").lower()
        extension = (stream_info.extension or "").lower()

        if extension in OFFICE_FILE_EXTENSIONS + OTHER_FILE_EXTENSIONS:
            return True

        for prefix in OFFICE_MIME_TYPE_PREFIXES + OTHER_MIME_TYPE_PREFIXES:
            if mimetype.startswith(prefix):
                return True

        return False

    def _analysis_features(self, stream_info: StreamInfo) -> List[str]:
        """
        Helper needed to determine which analysis features to use.
        Certain document analysis features are not availiable for
        office filetypes (.xlsx, .pptx, .html, .docx)
        """
        mimetype = (stream_info.mimetype or "").lower()
        extension = (stream_info.extension or "").lower()

        if extension in OFFICE_FILE_EXTENSIONS:
            return []

        for prefix in OFFICE_MIME_TYPE_PREFIXES:
            if mimetype.startswith(prefix):
                return []

        return [
            DocumentAnalysisFeature.FORMULAS,  # enable formula extraction
            DocumentAnalysisFeature.OCR_HIGH_RESOLUTION,  # enable high resolution OCR
            DocumentAnalysisFeature.STYLE_FONT,  # enable font style extraction
        ]

    def convert(
        self,
        file_stream: BinaryIO,
        stream_info: StreamInfo,
        **kwargs: Any,  # Options to pass to the converter
    ) -> DocumentConverterResult:
        # Extract the text using Azure Document Intelligence
        poller = self.doc_intel_client.begin_analyze_document(
            model_id="prebuilt-layout",
            body=AnalyzeDocumentRequest(bytes_source=file_stream.read()),
            features=self._analysis_features(stream_info),
            output_content_format=CONTENT_FORMAT,  # TODO: replace with "ContentFormat.MARKDOWN" when the bug is fixed
        )
        result: AnalyzeResult = poller.result()

        # remove comments from the markdown content generated by Doc Intelligence and append to markdown string
        markdown_text = re.sub(r"<!--.*?-->", "", result.content, flags=re.DOTALL)
        return DocumentConverterResult(markdown=markdown_text)
