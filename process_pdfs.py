import json
import re
from pathlib import Path
import fitz 
from concurrent.futures import ThreadPoolExecutor, as_completed
import os
class PDFProcessor:
    def __init__(self):
        self.title_cache = {}
        self.outline_cache = {}
    @staticmethod
    def clean_text(text):
        text=re.sub(r'---+','',text)  
        text=re.sub(r'(\w)-\s+(\w)',r'\1\2',text) 
        text=re.sub(r'[\n\r\t]+',' ',text)
        text=re.sub(r'[ ]{2,}',' ',text)
        return text.strip()

    def extract_title(self, page):
        cache_key=id(page)
        if cache_key in self.title_cache:
            return self.title_cache[cache_key]
        try:
            blocks=page.get_text("dict").get("blocks", [])
        except Exception:
            blocks=[]
        candidates=[]
        for block in blocks:
            for line in block.get("lines",[]):
                for span in line.get("spans",[]):
                    text = self.clean_text(span.get("text",""))
                    if len(text) < 5:
                        continue
                    if re.match(r'^[-=\s]+$',text): 
                        continue
                    if re.match(r'^\d+$',text): 
                        continue
                    size=span.get("size", 0)
                    y_pos=span.get("origin", [0, 0])[1]
                    weight=(size * 1.5) - (y_pos / page.rect.height)
                    candidates.append((weight, size, text))
        if not candidates:
            title="Untitled Document"
        else:
            candidates.sort(reverse=True)
            top_text=candidates[0][2]
            title=top_text if len(top_text) >= 8 else "Untitled Document"

        self.title_cache[cache_key]=title
        return title

    def extract_page_outline(self, page_num, page):
        outline_items=[]
        try:
            words_with_style=page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE).get("blocks", [])
            raw_words=page.get_text("words", sort=True)
        except Exception:
            return []

        span_size_map={}
        for block in words_with_style:
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    text=self.clean_text(span.get('text', ''))
                    if text:
                        span_size_map[text]=span.get('size', 0)

        lines={}
        for word in raw_words:
            y=round(word[3], 1)
            lines.setdefault(y, []).append(word[4])

        for y, words_in_line in sorted(lines.items()):
            line_text=self.clean_text(' '.join(words_in_line))

            if not line_text or len(line_text) < 5:
                continue

            if re.match(r'^[A-Z\s\W\d]{5,}$', line_text) or 'http' in line_text.lower():
                continue

            max_size = max([span_size_map.get(span_text, 0) for span_text in span_size_map if span_text in line_text] or [0])

            if max_size >= 12:
                level = (
                    "H1" if max_size >= 20 else
                    "H2" if max_size >= 16 else
                    "H3" if max_size >= 14 else
                    "H4"
                )
                outline_items.append({
                    "level": level,
                    "text": line_text,
                    "page": page_num + 1
                })

        return outline_items

    def extract_outline(self, doc):
        cache_key = id(doc)
        if cache_key in self.outline_cache:
            return self.outline_cache[cache_key]

        outline = []
        seen_texts = set()
        max_pages = min(len(doc), 50)

        title = self.title_cache.get(id(doc), '').lower().replace(' ', '')

        with ThreadPoolExecutor() as executor:
            futures = []
            for page_num in range(max_pages):
                try:
                    page = doc.load_page(page_num)
                    futures.append(executor.submit(self.extract_page_outline, page_num, page))
                except Exception as e:
                    print(f"Error loading page {page_num}: {str(e)}")

            for future in as_completed(futures):
                try:
                    items = future.result()
                    for item in items:
                        normalized_text = item['text'].lower().replace(' ', '')
                        if normalized_text == title:
                            continue
                        text_key = f"{item['text']}-{item['page']}"
                        if text_key not in seen_texts:
                            seen_texts.add(text_key)
                            outline.append(item)
                            if len(outline) >= 50:
                                break
                    if len(outline) >= 50:
                        break
                except Exception as e:
                    print(f"Error processing page result: {str(e)}")

        outline.sort(key=lambda x: x['page'])
        self.outline_cache[cache_key] = outline[:50]
        return outline[:50]

    def process_pdf(self, pdf_path, output_dir):
        try:
            with fitz.open(pdf_path) as doc:
                if len(doc) == 0:
                    raise ValueError("PDF has no pages")

                title = self.extract_title(doc[0])
                self.title_cache[id(doc)] = title
                outline = self.extract_outline(doc)

                result = {
                    "title": title,
                    "outline": outline
                }

                output_path = output_dir / f"{pdf_path.stem}.json"
                os.makedirs(output_dir, exist_ok=True)
                with open(output_path, 'w', encoding='utf-8') as f:
                    json.dump(result, f, indent=2, ensure_ascii=False)

            return True, pdf_path.name
        except Exception as e:
            return False, f"{pdf_path.name}: {str(e)}"

    def process_pdfs(self):
        input_dir=Path("/app/input")
        output_dir=Path("/app/output")
        output_dir.mkdir(exist_ok=True, parents=True)

        pdf_files=list(input_dir.glob("*.pdf"))
        total_files=len(pdf_files)
        processed_count=0
        errors=[]

        print(f"Found {total_files} PDF files to process")

        with ThreadPoolExecutor() as executor:
            futures=[executor.submit(self.process_pdf, pdf_file, output_dir) for pdf_file in pdf_files]

            for future in as_completed(futures):
                success, message=future.result()
                if success:
                    processed_count+=1
                    print(f"Processed: {message}")
                else:
                    errors.append(message)
                    print(f"Error: {message}")

        print(f"\nProcessing complete. Success: {processed_count}/{total_files}")
        if errors:
            print("\nErrors encountered:")
            for error in errors:
                print(f"- {error}")


if __name__ == "__main__":
    processor=PDFProcessor()
    processor.process_pdfs()
