# ingestion/plugins/uscode.py
import logging
import os
import re
from pathlib import Path
from typing import Dict, List, Optional

from bs4 import BeautifulSoup, Comment

from core.base_ingestor import BaseIngestor

logger = logging.getLogger(__name__)


class USCodeIngestor(BaseIngestor):
    """
    Ingestor for US Code documents.

    Uses citation-centric schema (v2.0):
    - Inserts text chunks into legal_chunks
    - Inserts PDF/HTML links into legal_artifacts
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.uscode_dir = self._resolve_uscode_dir()
        logger.info(f"US Code directory: {self.uscode_dir}")

    def _resolve_uscode_dir(self) -> Path:
        """
        Resolve US Code directory from known locations.

        Priority:
        1. USCODE_DATA_DIR / CASETALLY_USCODE_DIR env vars
        2. --data-dir/uscode
        3. --data-dir (if it already contains html files)
        4. workspace sibling: casetally-data-archive/uscode
        """
        candidates: List[Path] = []

        for env_var in ("USCODE_DATA_DIR", "CASETALLY_USCODE_DIR"):
            env_path = os.getenv(env_var)
            if env_path:
                candidates.append(Path(env_path))

        candidates.append(self.data_dir / "uscode")
        candidates.append(self.data_dir)

        for parent in Path(__file__).resolve().parents:
            candidates.append(parent / "casetally-data-archive" / "uscode")

        seen = set()
        ordered_candidates: List[Path] = []
        for path in candidates:
            key = str(path.resolve()) if path.exists() else str(path)
            if key in seen:
                continue
            seen.add(key)
            ordered_candidates.append(path)

        for candidate in ordered_candidates:
            if candidate.is_dir() and any(candidate.glob("*.html")):
                return candidate

        candidate_list = ", ".join(str(path) for path in ordered_candidates)
        raise FileNotFoundError(
            "Could not locate US Code html files. "
            f"Checked: {candidate_list}"
        )

    def run(self, limit: Optional[int] = None) -> Dict:
        """
        Main ingestion workflow.

        Args:
            limit: Optional limit on number of files to process

        Returns:
            Statistics dictionary
        """
        stats = {
            "processed": 0,
            "inserted": 0,
            "updated": 0,
            "skipped": 0,
            "errors": 0,
            "chunks_created": 0,
            "chunks_updated": 0,
            "chunks_deactivated": 0,
            "artifacts_created": 0,
        }

        run_id = self.start_ingestion_run("uscode", "Federal")

        try:
            html_files = sorted(self.uscode_dir.glob("*.html"))

            if not html_files:
                logger.warning(f"No HTML files found in {self.uscode_dir}")
                self.complete_ingestion_run(run_id, error_message="No HTML files found")
                return stats

            logger.info(f"Found {len(html_files)} HTML files")

            if limit:
                html_files = html_files[:limit]
                logger.info(f"Processing limited to {limit} files")

            for html_file in html_files:
                try:
                    logger.info(f"Processing: {html_file.name}")

                    title_num = self._extract_title_number(html_file.name)
                    pdf_file = self._find_matching_pdf(title_num)
                    sections = self._parse_html_file(html_file, title_num, pdf_file)

                    if not sections:
                        logger.warning(f"No sections found in {html_file.name}")
                        stats["errors"] += 1
                        continue

                    logger.info(f"Found {len(sections)} sections in {html_file.name}")

                    for section in sections:
                        result = self.ingest_document(
                            citation=section["citation"],
                            content=section["content"],
                            jurisdiction="Federal",
                            document_type="US Code",
                            pdf_path=str(pdf_file) if pdf_file else None,
                            pdf_page=section.get("pdf_page"),
                            html_url=None,
                            metadata={
                                "title_number": title_num,
                                "section_number": section["section_num"],
                                "html_file_path": str(html_file),
                                "effective_date": section.get("effective_date"),
                                "tags": section.get("tags", []),
                                "version": "2024",
                            },
                        )

                        stats["chunks_created"] += result["chunks_created"]
                        stats["chunks_updated"] += result["chunks_updated"]
                        stats["artifacts_created"] += result["artifacts_created"]

                        if result["status"] == "inserted":
                            stats["inserted"] += 1
                        elif result["status"] == "updated":
                            stats["updated"] += 1
                        else:
                            stats["skipped"] += 1

                        processed_sections = stats["inserted"] + stats["updated"] + stats["skipped"]
                        if processed_sections > 0 and processed_sections % 50 == 0:
                            self.commit_batch()
                            logger.info(
                                f"Progress: inserted={stats['inserted']}, "
                                f"updated={stats['updated']}, skipped={stats['skipped']}, "
                                f"chunks(created={stats['chunks_created']}, updated={stats['chunks_updated']}, "
                                f"deactivated={stats['chunks_deactivated']}), "
                                f"artifacts={stats['artifacts_created']}"
                            )

                    stats["processed"] += 1

                except Exception as e:
                    logger.error(f"Error processing {html_file.name}: {e}", exc_info=True)
                    stats["errors"] += 1
                    continue

            # Deactivation runs once for the whole corpus, after every file has
            # been seen, so a citation appearing in more than one place cannot
            # retire the chunks written by its own earlier occurrence.
            stats["chunks_deactivated"] = self.finalize_deactivation()

            self.commit_batch()

            self.complete_ingestion_run(
                run_id,
                chunks_added=stats["chunks_created"],
                chunks_updated=stats["chunks_updated"],
                artifacts_added=stats["artifacts_created"],
            )

            logger.info("=" * 60)
            logger.info("Ingestion complete!")
            logger.info(f"Files processed: {stats['processed']}")
            logger.info(f"Sections inserted: {stats['inserted']}")
            logger.info(f"Sections updated: {stats['updated']}")
            logger.info(f"Sections skipped: {stats['skipped']}")
            logger.info(f"Errors: {stats['errors']}")
            logger.info(f"Chunks created: {stats['chunks_created']}")
            logger.info(f"Chunks updated: {stats['chunks_updated']}")
            logger.info(f"Chunks deactivated: {stats['chunks_deactivated']}")
            logger.info(f"Artifacts created: {stats['artifacts_created']}")
            logger.info("=" * 60)

        except Exception as e:
            logger.error(f"Ingestion run failed: {e}", exc_info=True)
            self.complete_ingestion_run(run_id, error_message=str(e))
            raise

        return stats

    def _extract_title_number(self, filename: str) -> str:
        """
        Extract title number from filename.

        Examples:
            "U.S.C. Title 18 - CRIMES.html" -> "18"
            "title_18.html" -> "18"
        """
        patterns = [
            r"[Tt]itle[_\s]*(\d+)",
            r"USCODE.*?title(\d+)",
            r"t(\d+)",
        ]

        for pattern in patterns:
            match = re.search(pattern, filename)
            if match:
                return match.group(1)

        logger.warning(f"Could not extract title number from: {filename}")
        return "unknown"

    def _find_matching_pdf(self, title_num: str) -> Optional[Path]:
        """
        Find PDF file matching the title number.

        Looks for patterns like:
            USCODE-2024-title18.pdf
            USCODE-title18.pdf
            title18.pdf
        """
        if title_num == "unknown":
            return None

        patterns = [
            f"USCODE-*-title{title_num}.pdf",
            f"USCODE-title{title_num}.pdf",
            f"*title{title_num}*.pdf",
            f"usc{title_num.zfill(2)}.pdf",
        ]

        for pattern in patterns:
            matches = sorted(
                self.uscode_dir.glob(pattern),
                key=lambda p: (" copy" in p.stem.lower(), p.name),
            )
            if matches:
                logger.debug(f"Found PDF for title {title_num}: {matches[0].name}")
                return matches[0]

        logger.warning(f"No PDF found for title {title_num}")
        return None

    def _parse_html_file(
        self,
        html_file: Path,
        title_num: str,
        pdf_file: Optional[Path],
    ) -> List[Dict]:
        """
        Parse HTML file and extract sections.

        Args:
            html_file: Path to HTML file
            title_num: Title number
            pdf_file: Path to matching PDF (optional)

        Returns:
            List of section dictionaries
        """
        sections: List[Dict] = []

        with open(html_file, "r", encoding="utf-8") as f:
            html_content = f.read()

        soup = BeautifulSoup(html_content, "html.parser")
        section_headers = soup.find_all("h3", class_="section-head")

        if section_headers:
            logger.debug(f"Found {len(section_headers)} section headings")

            for heading in section_headers:
                heading_text = self._clean_text(heading.get_text(" ", strip=True))
                match = re.match(r"^[\u00a7]?\s*([0-9A-Za-z.\-]+)\.?\s*(.*)$", heading_text)
                if not match:
                    continue

                section_num = match.group(1)
                section_title = match.group(2).strip() or f"Section {section_num}"
                pdf_page = self._extract_pdf_page_near_heading(heading)

                content_parts: List[str] = []
                for sibling in heading.next_siblings:
                    sibling_name = getattr(sibling, "name", None)
                    if sibling_name == "h3" and "section-head" in (sibling.get("class") or []):
                        break

                    if not hasattr(sibling, "get_text"):
                        continue

                    if sibling_name == "p":
                        classes = sibling.get("class") or []
                        if classes and not any(cls.startswith("statutory-body") for cls in classes):
                            continue

                    part_text = self._clean_text(sibling.get_text(" ", strip=True))
                    if part_text:
                        content_parts.append(part_text)

                section_text = self._clean_text("\n".join(content_parts))
                if not section_text or len(section_text) < 30:
                    continue

                sections.append(
                    {
                        "section_num": section_num,
                        "title": f"{title_num} U.S.C. \u00a7 {section_num} - {section_title}",
                        "citation": f"{title_num} U.S.C. \u00a7 {section_num}",
                        "content": section_text,
                        "pdf_page": pdf_page,
                        "tags": [f"title:{title_num}", f"section:{section_num}"],
                    }
                )

        if not sections:
            logger.warning(f"No sections parsed, treating {html_file.name} as single document")
            clean_content = self._clean_text(soup.get_text(separator="\n", strip=True))
            if clean_content and len(clean_content) >= 100:
                sections.append(
                    {
                        "section_num": "1",
                        "title": f"United States Code - Title {title_num}",
                        "citation": f"{title_num} U.S.C.",
                        "content": clean_content,
                        "tags": [f"title:{title_num}"],
                    }
                )

        return sections

    def _extract_pdf_page_near_heading(self, heading) -> Optional[int]:
        """Find closest documentPDFPage/PDFPage comment before a section heading."""
        for node in heading.previous_elements:
            if getattr(node, "name", None) == "h3" and "section-head" in (node.get("class") or []):
                break

            if isinstance(node, Comment):
                comment_text = str(node)
                match = re.search(r"documentPDFPage:(\d+)", comment_text)
                if match:
                    return int(match.group(1))
                match = re.search(r"PDFPage:(\d+)", comment_text)
                if match:
                    return int(match.group(1))

        return None

    def _clean_text(self, text: str) -> str:
        """
        Clean and normalize text.

        - Remove excessive newlines
        - Normalize whitespace
        - Remove special characters
        """
        text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text)
        text = re.sub(r" +", " ", text)
        text = re.sub(r"\t+", " ", text)

        # Normalize common encoding artifact seen in source snapshots.
        text = text.replace("\u00c2\u00a7", "\u00a7")

        # Remove zero-width characters.
        text = re.sub(r"[\u200b-\u200d\ufeff]", "", text)
        return text.strip()
