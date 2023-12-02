import os
from PIL import Image, ImageDraw
from reportlab.pdfgen import canvas

def mm_to_points(mm):
    """Converts millimeters to points (1 point = 1/72 inches)."""
    return int((mm * 72) / 25.4)

def read_png_files(directory):
    """Returns a sorted list of PNG file names from the specified directory."""
    return sorted(f for f in os.listdir(directory) if f.endswith('.png'))

def resize_images(image_files, directory, size):
    """
    Yields resized images from a list of image filenames.

    Args:
    - image_files: List of filenames.
    - directory: Path to the image files.
    - size: Tuple (width, height) to resize images to.
    """
    for filename in image_files:
        with Image.open(os.path.join(directory, filename)) as img:
            yield img.resize(size, Image.LANCZOS)

def draw_grid(draw, num_rows, num_cols, cell_width, cell_height, x_margin, y_margin, page_size, bleed=10):
    """
    Draws a grid on the image canvas to separate cards.

    Args:
    - draw: ImageDraw object for drawing on the canvas.
    - num_rows, num_cols: Grid dimensions.
    - cell_width, cell_height: Dimensions of each grid cell.
    - x_margin, y_margin: Margins from the edges of the page.
    - page_size: Size of the PDF page.
    - bleed: Extra line length for aesthetics.
    """
    x_bleed, y_bleed = x_margin - bleed, y_margin - bleed
    for row in range(num_rows + 1):
        y = row * cell_height + y_margin
        draw.line([(x_bleed, y), (page_size[0] - x_bleed, y)], fill="black")
    for col in range(num_cols + 1):
        x = col * cell_width + x_margin
        draw.line([(x, y_bleed), (x, page_size[1] - y_bleed)], fill="black")

def create_pdf(images, page_size, grid_size, card_size, output_pdf):
    """
    Creates a PDF file from a list of images, placing them in a grid.

    Args:
    - images: List of PIL Image objects.
    - page_size: Size of the PDF page (width, height).
    - grid_size: Grid size as (num_cols, num_rows).
    - card_size: Size of individual cards (width, height).
    - output_pdf: Output PDF file path.
    """
    x_margin, y_margin = [(page - grid * card) // 2 for page, grid, card in zip(page_size, grid_size, card_size)]
    c = canvas.Canvas(output_pdf, pagesize=page_size)

    images_per_page = grid_size[0] * grid_size[1]
    for page in range(0, len(images), images_per_page):
        combined_image = Image.new('RGB', page_size, "white")
        draw = ImageDraw.Draw(combined_image)

        for idx in range(images_per_page):
            if page + idx >= len(images): break
            image = images[page + idx]
            row, col = divmod(idx, grid_size[0])
            x_offset, y_offset = col * card_size[0] + x_margin, row * card_size[1] + y_margin
            combined_image.paste(image, (x_offset, y_offset))

        draw_grid(draw, grid_size[1], grid_size[0], card_size[0], card_size[1], x_margin, y_margin, page_size)
        temp_image_path = f"temp_page_{page}.png"
        combined_image.save(temp_image_path)
        c.drawImage(temp_image_path, 0, 0, width=page_size[0], height=page_size[1])
        c.showPage()
        os.remove(temp_image_path)

    c.save()


def main():
    IMAGE_DIR = "all_files"
    SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
    OUTPUT_PDF = os.path.join(SCRIPT_DIR, "combined_cards.pdf")
    PAGE_SIZE = (595, 842)  # A4 in points
    GRID_SIZE = (3, 3)  # 3x3 grid
    CARD_SIZE = (mm_to_points(63), mm_to_points(88))

    print("Step 1: Reading PNG Files")
    image_files = read_png_files(IMAGE_DIR)

    print("Step 2: Resizing Images")
    resized_images = list(resize_images(image_files, IMAGE_DIR, CARD_SIZE))

    print("Step 3: Creating PDF")
    create_pdf(resized_images, PAGE_SIZE, GRID_SIZE, CARD_SIZE, OUTPUT_PDF)

    print("Completed. PDF saved as:", OUTPUT_PDF)

if __name__ == "__main__":
    main()