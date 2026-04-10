# ingestion/core/chunker.py
import re
from typing import List, Dict


class TextChunker:
    """
    Intelligent text chunking with overlap.
    
    Creates chunks suitable for semantic search while preserving context.
    """
    
    def __init__(self, chunk_size: int = 512, overlap: int = 50):
        """
        Args:
            chunk_size: Target chunk size in words
            overlap: Number of words to overlap between chunks
        """
        self.chunk_size = chunk_size
        self.overlap = overlap
    
    def chunk_text(self, text: str) -> List[Dict]:
        """
        Chunk text into overlapping segments.
        
        Args:
            text: Input text to chunk
            
        Returns:
            List of chunk dictionaries with metadata
        """
        # Clean and normalize text
        text = self._clean_text(text)
        
        if not text:
            return []
        
        # Split into words
        words = text.split()
        
        if len(words) <= self.chunk_size:
            # Text is smaller than chunk size - single chunk
            return [{
                'text': text,
                'token_count': len(words),
                'start_pos': 0,
                'end_pos': len(words),
                'type': 'paragraph'
            }]
        
        chunks = []
        start = 0
        
        while start < len(words):
            # Extract chunk
            end = min(start + self.chunk_size, len(words))
            chunk_words = words[start:end]
            chunk_text = ' '.join(chunk_words)
            
            # Create chunk metadata
            chunks.append({
                'text': chunk_text,
                'token_count': len(chunk_words),
                'start_pos': start,
                'end_pos': end,
                'type': 'paragraph'
            })
            
            # Move to next chunk with overlap
            if end >= len(words):
                break
            
            start += (self.chunk_size - self.overlap)
        
        return chunks
    
    def chunk_by_section(self, text: str, section_marker: str = "\n\n") -> List[Dict]:
        """
        Chunk text by logical sections (paragraphs, sections).
        
        Args:
            text: Input text
            section_marker: Delimiter for sections
            
        Returns:
            List of section-based chunks
        """
        sections = text.split(section_marker)
        chunks = []
        position = 0
        
        for idx, section in enumerate(sections):
            section = section.strip()
            if not section:
                continue
            
            words = section.split()
            
            chunks.append({
                'text': section,
                'token_count': len(words),
                'start_pos': position,
                'end_pos': position + len(words),
                'type': 'section'
            })
            
            position += len(words)
        
        return chunks
    
    def _clean_text(self, text: str) -> str:
        """Clean and normalize text."""
        # Remove excessive whitespace
        text = re.sub(r'\s+', ' ', text)
        
        # Remove control characters
        text = re.sub(r'[\x00-\x08\x0b-\x0c\x0e-\x1f\x7f-\x9f]', '', text)
        
        return text.strip()