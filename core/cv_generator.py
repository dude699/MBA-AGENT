"""
============================================================
PRISM v0.1 — CV GENERATOR ENGINE (WEASYPRINT PDF)
============================================================
Professional PDF CV/resume generation engine for per-application
tailoring. Takes ATS keyword gaps from A-10 and rewrites bullet
points to maximize ATS pass rate while maintaining truthfulness.

Architecture:
    - HTML template → CSS styling → WeasyPrint PDF rendering
    - Bullet rewrite injection from A-18 CV Enhancer
    - Section-aware editing (only modifies relevant sections)
    - Professional template with clean typography
    - Consistent branding across all generated CVs
    - File naming: CV_{candidate}_{company}_{date}.pdf

Used By:
    A-18: CV Intelligence Enhancer — Tailors CV per application
    A-13: Auto Applier — Attaches tailored CV to applications
    A-10: ATS Simulator — Generates optimized CV after simulation

Output:
    - PDF file saved to data/cvs/ directory
    - Path stored in application_packages.tailored_cv_url

Dependencies:
    - weasyprint>=60.0 (pip install weasyprint)
    - System: libpango, libcairo (usually pre-installed on Render)

Cost: $0 — WeasyPrint is fully open-source
============================================================
"""

import os
import sys
import re
import time
import hashlib
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import (
    Dict, List, Optional, Tuple, Any, Union
)
from dataclasses import dataclass, field

try:
    from loguru import logger
except ImportError:
    import logging
    logger = logging.getLogger(__name__)


# ============================================================
# CONSTANTS
# ============================================================

CV_OUTPUT_DIR = "data/cvs"
DEFAULT_CANDIDATE_NAME = "Abuzar Khan"
DEFAULT_COLLEGE = "Aligarh Muslim University"
DEFAULT_DEGREE = "MBA"
DEFAULT_YEAR = "2025"
DEFAULT_PHONE = ""
DEFAULT_EMAIL = ""
DEFAULT_LINKEDIN = ""
DEFAULT_GITHUB = ""

MAX_BULLET_LENGTH = 200
MAX_BULLETS_PER_SECTION = 6
MAX_SKILLS_DISPLAY = 15


# ============================================================
# DATA MODELS
# ============================================================

@dataclass
class CVSection:
    """A section of the CV (e.g., Education, Experience, Skills)."""
    title: str
    section_type: str  # education, experience, skills, projects, certifications, summary
    entries: List[Dict[str, Any]] = field(default_factory=list)
    order: int = 0
    visible: bool = True


@dataclass
class CVExperienceEntry:
    """A single experience/internship entry."""
    company: str
    role: str
    location: str = ""
    start_date: str = ""
    end_date: str = ""
    is_current: bool = False
    bullets: List[str] = field(default_factory=list)
    keywords_added: List[str] = field(default_factory=list)


@dataclass
class CVEducationEntry:
    """A single education entry."""
    institution: str
    degree: str
    field_of_study: str = ""
    start_year: str = ""
    end_year: str = ""
    gpa: str = ""
    achievements: List[str] = field(default_factory=list)


@dataclass
class CVProfile:
    """Complete candidate CV profile."""
    name: str = DEFAULT_CANDIDATE_NAME
    email: str = DEFAULT_EMAIL
    phone: str = DEFAULT_PHONE
    linkedin: str = DEFAULT_LINKEDIN
    github: str = DEFAULT_GITHUB
    location: str = "India"
    # Summary
    summary: str = ""
    # Sections
    education: List[CVEducationEntry] = field(default_factory=list)
    experience: List[CVExperienceEntry] = field(default_factory=list)
    skills: Dict[str, List[str]] = field(default_factory=dict)
    certifications: List[str] = field(default_factory=list)
    projects: List[Dict[str, Any]] = field(default_factory=list)
    achievements: List[str] = field(default_factory=list)
    languages: List[str] = field(default_factory=list)
    interests: List[str] = field(default_factory=list)


@dataclass
class CVTailoringRequest:
    """Request to tailor a CV for a specific application."""
    profile: CVProfile
    target_company: str
    target_role: str
    target_jd: str = ""
    # From A-10 ATS Simulator
    keyword_gaps: List[str] = field(default_factory=list)
    bullet_rewrites: List[Dict[str, str]] = field(default_factory=list)
    skills_to_highlight: List[str] = field(default_factory=list)
    # From A-20 Deep Company Intel
    company_hooks: List[str] = field(default_factory=list)
    # Output preferences
    include_summary: bool = True
    include_projects: bool = True
    max_pages: int = 1


@dataclass
class CVGenerationResult:
    """Result of a CV generation."""
    success: bool
    pdf_path: str = ""
    file_size_bytes: int = 0
    generation_time_ms: float = 0.0
    keywords_injected: List[str] = field(default_factory=list)
    bullets_rewritten: int = 0
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            'success': self.success,
            'pdf_path': self.pdf_path,
            'file_size_bytes': self.file_size_bytes,
            'generation_time_ms': round(self.generation_time_ms, 1),
            'keywords_injected': self.keywords_injected,
            'bullets_rewritten': self.bullets_rewritten,
            'error': self.error,
        }


# ============================================================
# HTML/CSS TEMPLATE
# ============================================================

CV_CSS_TEMPLATE = """
/* PRISM v0.1 — Professional CV Template */
@page {
    size: A4;
    margin: 15mm 18mm 15mm 18mm;
}

* {
    margin: 0;
    padding: 0;
    box-sizing: border-box;
}

body {
    font-family: 'Helvetica Neue', Arial, sans-serif;
    font-size: 10pt;
    line-height: 1.35;
    color: #1a1a1a;
    background: white;
}

.cv-container {
    max-width: 100%;
}

/* Header */
.cv-header {
    text-align: center;
    margin-bottom: 8pt;
    padding-bottom: 6pt;
    border-bottom: 2pt solid #2c3e50;
}

.cv-name {
    font-size: 20pt;
    font-weight: 700;
    color: #2c3e50;
    letter-spacing: 1pt;
    margin-bottom: 4pt;
}

.cv-contact {
    font-size: 9pt;
    color: #555;
    line-height: 1.5;
}

.cv-contact a {
    color: #2c3e50;
    text-decoration: none;
}

.cv-contact .separator {
    color: #999;
    margin: 0 6pt;
}

/* Section headers */
.section-title {
    font-size: 11pt;
    font-weight: 700;
    color: #2c3e50;
    text-transform: uppercase;
    letter-spacing: 0.5pt;
    margin-top: 10pt;
    margin-bottom: 4pt;
    padding-bottom: 2pt;
    border-bottom: 1pt solid #bdc3c7;
}

/* Experience entries */
.entry {
    margin-bottom: 6pt;
}

.entry-header {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    margin-bottom: 2pt;
}

.entry-title {
    font-weight: 700;
    font-size: 10pt;
    color: #1a1a1a;
}

.entry-company {
    font-weight: 600;
    font-size: 10pt;
    color: #2c3e50;
}

.entry-meta {
    font-size: 9pt;
    color: #666;
    font-style: italic;
}

.entry-dates {
    font-size: 9pt;
    color: #666;
    text-align: right;
    white-space: nowrap;
}

.entry-location {
    font-size: 9pt;
    color: #666;
}

/* Bullet points */
.bullets {
    margin-left: 14pt;
    margin-top: 2pt;
}

.bullets li {
    font-size: 9.5pt;
    line-height: 1.35;
    margin-bottom: 1.5pt;
    text-align: justify;
}

.keyword-highlight {
    font-weight: 600;
}

/* Skills */
.skills-grid {
    display: flex;
    flex-wrap: wrap;
    gap: 2pt 12pt;
    margin-top: 3pt;
}

.skill-category {
    margin-bottom: 3pt;
    font-size: 9.5pt;
}

.skill-category-name {
    font-weight: 700;
    color: #2c3e50;
}

.skill-items {
    color: #333;
}

/* Education */
.edu-entry {
    margin-bottom: 4pt;
}

.edu-degree {
    font-weight: 700;
    font-size: 10pt;
}

.edu-institution {
    font-size: 9.5pt;
    color: #2c3e50;
}

.edu-details {
    font-size: 9pt;
    color: #666;
}

/* Summary */
.summary-text {
    font-size: 9.5pt;
    line-height: 1.4;
    color: #333;
    text-align: justify;
    margin-top: 3pt;
}

/* Certifications, Achievements */
.simple-list {
    margin-left: 14pt;
    margin-top: 3pt;
}

.simple-list li {
    font-size: 9.5pt;
    line-height: 1.35;
    margin-bottom: 1.5pt;
}

/* Tailoring badge (hidden in production) */
.tailored-for {
    display: none;
}
"""


def _generate_cv_html(
    profile: CVProfile,
    request: CVTailoringRequest,
) -> str:
    """Generate the full HTML for a CV."""
    sections = []

    # === HEADER ===
    contact_parts = []
    if profile.email:
        contact_parts.append(f'<a href="mailto:{profile.email}">{profile.email}</a>')
    if profile.phone:
        contact_parts.append(profile.phone)
    if profile.location:
        contact_parts.append(profile.location)
    if profile.linkedin:
        contact_parts.append(f'<a href="{profile.linkedin}">LinkedIn</a>')
    if profile.github:
        contact_parts.append(f'<a href="{profile.github}">GitHub</a>')

    contact_line = '<span class="separator">|</span>'.join(contact_parts)

    header = f"""
    <div class="cv-header">
        <div class="cv-name">{profile.name}</div>
        <div class="cv-contact">{contact_line}</div>
    </div>"""
    sections.append(header)

    # === SUMMARY ===
    if request.include_summary and profile.summary:
        summary_text = profile.summary
        # Inject company hooks if available
        if request.company_hooks:
            hook = request.company_hooks[0]
            if hook and hook not in summary_text:
                summary_text = f"{summary_text} {hook}"

        sections.append(f"""
    <div class="section-title">Professional Summary</div>
    <div class="summary-text">{summary_text}</div>""")

    # === EDUCATION ===
    if profile.education:
        edu_html = '<div class="section-title">Education</div>'
        for edu in profile.education:
            achievements_html = ""
            if edu.achievements:
                items = "".join(f"<li>{a}</li>" for a in edu.achievements[:3])
                achievements_html = f'<ul class="bullets">{items}</ul>'

            edu_html += f"""
    <div class="edu-entry">
        <div style="display:flex; justify-content:space-between;">
            <div>
                <span class="edu-degree">{edu.degree}</span>
                {f' in {edu.field_of_study}' if edu.field_of_study else ''}
                <span class="edu-institution"> — {edu.institution}</span>
            </div>
            <div class="entry-dates">{edu.start_year} – {edu.end_year}</div>
        </div>
        {f'<div class="edu-details">GPA: {edu.gpa}</div>' if edu.gpa else ''}
        {achievements_html}
    </div>"""
        sections.append(edu_html)

    # === EXPERIENCE ===
    if profile.experience:
        exp_html = '<div class="section-title">Experience</div>'

        # Build a lookup for bullet rewrites
        rewrite_map = {}
        for rw in request.bullet_rewrites:
            original = rw.get('original', '').strip().lower()
            improved = rw.get('improved', '')
            if original and improved:
                rewrite_map[original] = improved

        bullets_rewritten = 0

        for exp in profile.experience:
            date_str = f"{exp.start_date} – {'Present' if exp.is_current else exp.end_date}"
            location_str = f" | {exp.location}" if exp.location else ""

            # Process bullets with rewrites
            processed_bullets = []
            for bullet in exp.bullets[:MAX_BULLETS_PER_SECTION]:
                bullet_lower = bullet.strip().lower()
                if bullet_lower in rewrite_map:
                    processed_bullets.append(rewrite_map[bullet_lower])
                    bullets_rewritten += 1
                else:
                    # Check partial matches
                    matched = False
                    for orig_key, improved_val in rewrite_map.items():
                        if orig_key in bullet_lower or bullet_lower in orig_key:
                            processed_bullets.append(improved_val)
                            bullets_rewritten += 1
                            matched = True
                            break
                    if not matched:
                        processed_bullets.append(bullet)

            # Highlight keywords in bullets
            highlighted_bullets = []
            for bullet in processed_bullets:
                for kw in request.skills_to_highlight[:5]:
                    pattern = re.compile(re.escape(kw), re.IGNORECASE)
                    bullet = pattern.sub(
                        f'<span class="keyword-highlight">{kw}</span>',
                        bullet,
                        count=1
                    )
                highlighted_bullets.append(bullet)

            bullets_html = ""
            if highlighted_bullets:
                items = "".join(
                    f"<li>{b[:MAX_BULLET_LENGTH]}</li>"
                    for b in highlighted_bullets
                )
                bullets_html = f'<ul class="bullets">{items}</ul>'

            exp_html += f"""
    <div class="entry">
        <div style="display:flex; justify-content:space-between;">
            <div>
                <span class="entry-title">{exp.role}</span>
                <span class="entry-company"> — {exp.company}</span>
                <span class="entry-location">{location_str}</span>
            </div>
            <div class="entry-dates">{date_str}</div>
        </div>
        {bullets_html}
    </div>"""

        sections.append(exp_html)

    # === SKILLS ===
    if profile.skills:
        skills_html = '<div class="section-title">Skills</div><div class="skills-grid">'

        # Prioritize skills that match keyword gaps
        for category, skill_list in profile.skills.items():
            # Move matching skills to front
            prioritized = []
            remaining = []
            for skill in skill_list:
                if any(
                    gap.lower() in skill.lower() or skill.lower() in gap.lower()
                    for gap in request.keyword_gaps
                ):
                    prioritized.append(f'<b>{skill}</b>')
                else:
                    remaining.append(skill)
            all_skills = prioritized + remaining
            skills_str = ", ".join(all_skills[:MAX_SKILLS_DISPLAY])

            skills_html += f"""
        <div class="skill-category">
            <span class="skill-category-name">{category}:</span>
            <span class="skill-items">{skills_str}</span>
        </div>"""

        skills_html += '</div>'
        sections.append(skills_html)

    # === PROJECTS ===
    if request.include_projects and profile.projects:
        proj_html = '<div class="section-title">Projects</div>'
        for proj in profile.projects[:3]:
            proj_name = proj.get('name', '')
            proj_desc = proj.get('description', '')
            proj_tech = proj.get('technologies', [])
            tech_str = f" ({', '.join(proj_tech)})" if proj_tech else ""

            proj_html += f"""
    <div class="entry">
        <div class="entry-title">{proj_name}{tech_str}</div>
        <div style="font-size: 9.5pt; margin-top: 1pt;">{proj_desc}</div>
    </div>"""
        sections.append(proj_html)

    # === CERTIFICATIONS ===
    if profile.certifications:
        cert_items = "".join(
            f"<li>{c}</li>" for c in profile.certifications[:5]
        )
        sections.append(f"""
    <div class="section-title">Certifications</div>
    <ul class="simple-list">{cert_items}</ul>""")

    # === ACHIEVEMENTS ===
    if profile.achievements:
        ach_items = "".join(
            f"<li>{a}</li>" for a in profile.achievements[:5]
        )
        sections.append(f"""
    <div class="section-title">Achievements</div>
    <ul class="simple-list">{ach_items}</ul>""")

    # === LANGUAGES ===
    if profile.languages:
        lang_str = " | ".join(profile.languages)
        sections.append(f"""
    <div class="section-title">Languages</div>
    <div style="font-size: 9.5pt; margin-top: 3pt;">{lang_str}</div>""")

    # Assemble full HTML
    body_content = "\n".join(sections)

    full_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>CV - {profile.name} - {request.target_company}</title>
    <style>{CV_CSS_TEMPLATE}</style>
</head>
<body>
    <div class="cv-container">
        {body_content}
    </div>
    <!-- Tailored for: {request.target_company} - {request.target_role} -->
</body>
</html>"""

    return full_html


# ============================================================
# MAIN CV GENERATOR ENGINE
# ============================================================

class CVGenerator:
    """
    PRISM v0.1 — CV/Resume PDF Generation Engine (Singleton).

    Generates professionally-formatted, ATS-optimized PDF resumes
    with per-application tailoring.

    Usage:
        gen = get_cv_generator()
        result = gen.generate_tailored_cv(request)
        result = gen.generate_from_profile(profile, company, role)
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True

        # Ensure output directory exists
        self._output_dir = Path(CV_OUTPUT_DIR)
        self._output_dir.mkdir(parents=True, exist_ok=True)

        # Check if WeasyPrint is available
        self._weasyprint_available = False
        try:
            import weasyprint
            self._weasyprint_available = True
            logger.info("[CV-GEN] WeasyPrint available for PDF generation")
        except ImportError:
            logger.warning(
                "[CV-GEN] WeasyPrint not installed! "
                "PDF generation will use HTML fallback. "
                "Install with: pip install weasyprint"
            )
        except Exception as e:
            logger.warning(f"[CV-GEN] WeasyPrint init warning: {e}")

        # Stats
        self._total_generated = 0
        self._total_failed = 0
        self._total_keywords_injected = 0
        self._total_bullets_rewritten = 0

        logger.info(
            f"[CV-GEN] Engine initialized "
            f"(output={self._output_dir}, "
            f"weasyprint={'YES' if self._weasyprint_available else 'NO'})"
        )

    @property
    def is_available(self) -> bool:
        """Check if PDF generation is available."""
        return self._weasyprint_available

    # ----------------------------------------------------------
    # CORE GENERATION
    # ----------------------------------------------------------

    def generate_tailored_cv(
        self,
        request: CVTailoringRequest,
    ) -> CVGenerationResult:
        """
        Generate a tailored CV PDF for a specific application.

        Args:
            request: CVTailoringRequest with profile, target, and ATS data

        Returns:
            CVGenerationResult with path to generated PDF
        """
        start_time = time.time()

        try:
            # Generate HTML
            html_content = _generate_cv_html(
                profile=request.profile,
                request=request,
            )

            # Generate filename
            company_slug = re.sub(
                r'[^a-zA-Z0-9]', '_', request.target_company
            )[:30].strip('_')
            date_str = datetime.now().strftime('%Y%m%d')
            filename = f"CV_{request.profile.name.replace(' ', '_')}_{company_slug}_{date_str}"

            # Generate PDF
            if self._weasyprint_available:
                pdf_path = self._generate_pdf(html_content, filename)
            else:
                # Fallback: save as HTML
                pdf_path = self._save_html_fallback(html_content, filename)

            if not pdf_path:
                return CVGenerationResult(
                    success=False,
                    error="PDF generation failed",
                    generation_time_ms=(time.time() - start_time) * 1000,
                )

            file_size = os.path.getsize(pdf_path) if os.path.exists(pdf_path) else 0
            generation_time_ms = (time.time() - start_time) * 1000

            # Track stats
            self._total_generated += 1
            keywords_injected = [
                kw for kw in request.keyword_gaps
                if kw.lower() in html_content.lower()
            ]
            self._total_keywords_injected += len(keywords_injected)
            bullets_rewritten = len(request.bullet_rewrites)
            self._total_bullets_rewritten += bullets_rewritten

            logger.info(
                f"[CV-GEN] Generated CV for {request.target_company} "
                f"({file_size} bytes, {generation_time_ms:.0f}ms, "
                f"{len(keywords_injected)} keywords, {bullets_rewritten} rewrites)"
            )

            return CVGenerationResult(
                success=True,
                pdf_path=pdf_path,
                file_size_bytes=file_size,
                generation_time_ms=generation_time_ms,
                keywords_injected=keywords_injected,
                bullets_rewritten=bullets_rewritten,
            )

        except Exception as e:
            self._total_failed += 1
            logger.error(f"[CV-GEN] Generation failed: {e}")
            return CVGenerationResult(
                success=False,
                error=str(e),
                generation_time_ms=(time.time() - start_time) * 1000,
            )

    def _generate_pdf(self, html_content: str, filename: str) -> Optional[str]:
        """Generate PDF using WeasyPrint."""
        try:
            import weasyprint

            pdf_path = str(self._output_dir / f"{filename}.pdf")
            doc = weasyprint.HTML(string=html_content)
            doc.write_pdf(pdf_path)

            if os.path.exists(pdf_path) and os.path.getsize(pdf_path) > 0:
                return pdf_path
            else:
                logger.error("[CV-GEN] PDF file empty or not created")
                return None

        except Exception as e:
            logger.error(f"[CV-GEN] WeasyPrint PDF generation error: {e}")
            return None

    def _save_html_fallback(self, html_content: str, filename: str) -> Optional[str]:
        """Save as HTML when WeasyPrint is not available."""
        try:
            html_path = str(self._output_dir / f"{filename}.html")
            with open(html_path, 'w', encoding='utf-8') as f:
                f.write(html_content)
            logger.warning(f"[CV-GEN] Saved HTML fallback: {html_path}")
            return html_path
        except Exception as e:
            logger.error(f"[CV-GEN] HTML fallback save error: {e}")
            return None

    # ----------------------------------------------------------
    # CONVENIENCE METHODS
    # ----------------------------------------------------------

    def generate_from_profile(
        self,
        profile: CVProfile,
        target_company: str,
        target_role: str,
        keyword_gaps: Optional[List[str]] = None,
        bullet_rewrites: Optional[List[Dict[str, str]]] = None,
    ) -> CVGenerationResult:
        """
        Simple generation from a profile without full tailoring request.

        Args:
            profile: Candidate CV profile
            target_company: Target company name
            target_role: Target role/position
            keyword_gaps: Optional ATS keyword gaps to address
            bullet_rewrites: Optional bullet point rewrites

        Returns:
            CVGenerationResult
        """
        request = CVTailoringRequest(
            profile=profile,
            target_company=target_company,
            target_role=target_role,
            keyword_gaps=keyword_gaps or [],
            bullet_rewrites=bullet_rewrites or [],
        )
        return self.generate_tailored_cv(request)

    def generate_base_cv(self, profile: CVProfile) -> CVGenerationResult:
        """
        Generate a base (non-tailored) CV from profile.
        Used as a starting template.
        """
        return self.generate_from_profile(
            profile=profile,
            target_company="General",
            target_role="MBA Intern",
        )

    # ----------------------------------------------------------
    # HTML PREVIEW
    # ----------------------------------------------------------

    def generate_html_preview(
        self,
        request: CVTailoringRequest,
    ) -> str:
        """
        Generate HTML preview of the CV (for mini-app display).

        Args:
            request: CV tailoring request

        Returns:
            HTML string for rendering in browser
        """
        return _generate_cv_html(
            profile=request.profile,
            request=request,
        )

    # ----------------------------------------------------------
    # FILE MANAGEMENT
    # ----------------------------------------------------------

    def get_generated_cvs(self) -> List[Dict[str, Any]]:
        """Get list of all generated CV files."""
        cvs = []
        for f in sorted(self._output_dir.glob("CV_*.*"), reverse=True):
            cvs.append({
                'filename': f.name,
                'path': str(f),
                'size_bytes': f.stat().st_size,
                'created': datetime.fromtimestamp(
                    f.stat().st_mtime
                ).isoformat(),
                'type': f.suffix,
            })
        return cvs

    def cleanup_old_cvs(self, keep_latest: int = 50) -> int:
        """Remove old CV files, keeping the latest N."""
        all_cvs = sorted(
            self._output_dir.glob("CV_*.*"),
            key=lambda f: f.stat().st_mtime,
            reverse=True
        )
        removed = 0
        for cv_file in all_cvs[keep_latest:]:
            try:
                cv_file.unlink()
                removed += 1
            except Exception:
                pass
        if removed > 0:
            logger.info(f"[CV-GEN] Cleaned up {removed} old CV files")
        return removed

    # ----------------------------------------------------------
    # HEALTH & MONITORING
    # ----------------------------------------------------------

    def get_health(self) -> Dict[str, Any]:
        """Get CV generator health and statistics."""
        cv_count = len(list(self._output_dir.glob("CV_*.*")))
        total_size = sum(
            f.stat().st_size
            for f in self._output_dir.glob("CV_*.*")
        )

        return {
            'weasyprint_available': self._weasyprint_available,
            'output_dir': str(self._output_dir),
            'total_generated': self._total_generated,
            'total_failed': self._total_failed,
            'total_keywords_injected': self._total_keywords_injected,
            'total_bullets_rewritten': self._total_bullets_rewritten,
            'stored_cvs': cv_count,
            'total_storage_mb': round(total_size / (1024 * 1024), 2),
        }


# ============================================================
# MODULE-LEVEL SINGLETON
# ============================================================

_generator_instance: Optional[CVGenerator] = None
_generator_lock = threading.Lock()


def get_cv_generator() -> CVGenerator:
    """Get the singleton CVGenerator instance."""
    global _generator_instance
    if _generator_instance is None:
        with _generator_lock:
            if _generator_instance is None:
                _generator_instance = CVGenerator()
    return _generator_instance


# ============================================================
# CLI / TESTING
# ============================================================

if __name__ == "__main__":
    print("=" * 60)
    print("PRISM v0.1 — CV Generator Engine Test")
    print("=" * 60)

    gen = get_cv_generator()
    health = gen.get_health()

    print(f"\nEngine Status:")
    print(f"  WeasyPrint: {'Available' if health['weasyprint_available'] else 'NOT AVAILABLE'}")
    print(f"  Output dir: {health['output_dir']}")
    print(f"  CVs stored: {health['stored_cvs']}")

    # Test generation with sample profile
    print("\n[TEST] Generating sample CV...")
    profile = CVProfile(
        name="Abuzar Khan",
        email="abuzar@example.com",
        phone="+91-9876543210",
        linkedin="https://linkedin.com/in/abuzarkhan",
        location="India",
        summary="Results-driven MBA candidate with expertise in marketing analytics, strategy, and data-driven decision making.",
        education=[
            CVEducationEntry(
                institution="Aligarh Muslim University",
                degree="MBA",
                field_of_study="Marketing & Strategy",
                start_year="2024",
                end_year="2026",
                gpa="8.5/10",
                achievements=["Dean's List", "Case Competition Winner"],
            ),
        ],
        experience=[
            CVExperienceEntry(
                company="XYZ Corp",
                role="Business Development Intern",
                location="Mumbai",
                start_date="May 2024",
                end_date="Jul 2024",
                bullets=[
                    "Led market research for 3 new product lines, resulting in 15% revenue growth",
                    "Developed financial models for M&A due diligence across 5 targets",
                    "Created investor deck that secured $2M seed funding",
                ],
            ),
        ],
        skills={
            'Technical': ['Python', 'SQL', 'Tableau', 'Excel', 'Power BI'],
            'Domain': ['Financial Modeling', 'Market Research', 'Strategy', 'Analytics'],
            'Soft Skills': ['Leadership', 'Communication', 'Problem Solving'],
        },
        certifications=[
            "Google Analytics Certified",
            "Bloomberg Market Concepts",
        ],
    )

    result = gen.generate_from_profile(
        profile=profile,
        target_company="McKinsey & Company",
        target_role="Summer Associate Intern",
        keyword_gaps=["management consulting", "client engagement", "problem solving"],
        bullet_rewrites=[{
            'original': "Led market research for 3 new product lines, resulting in 15% revenue growth",
            'improved': "Spearheaded management consulting-style market research across 3 product lines, driving 15% revenue growth through client engagement and data-driven strategy",
        }],
    )

    print(f"\n  Success: {result.success}")
    print(f"  Path: {result.pdf_path}")
    print(f"  Size: {result.file_size_bytes} bytes")
    print(f"  Time: {result.generation_time_ms:.0f}ms")
    print(f"  Keywords injected: {result.keywords_injected}")
    print(f"  Bullets rewritten: {result.bullets_rewritten}")

    print("\n" + "=" * 60)
