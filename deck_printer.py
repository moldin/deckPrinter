import os
from PIL import Image, ImageDraw
import os
from fpdf import FPDF
from tqdm import tqdm

# I want to switch the use of reportlab to fpdf

def mm_to_points(mm):
    """Converts millimeters to points (1 point = 1/72 inches)."""
    return int((mm * 72) / 25.4)

def read_png_files(directory):
    """Returns a sorted list of PNG file names from the specified directory."""
    return sorted(f for f in os.listdir(directory) if f.endswith('.png'))

def scale_image_to_card(img, card_size_pixels, x_crop=35, y_crop=35):
    """
    Scales an crops an image to fit within the card size in pixels while preserving aspect ratio.
    The image will fill the entire card space, and any overflow will be clipped.

    Args:
    - img: PIL Image object.
    - card_size_pixels: Tuple (width, height) of the card size in pixels.

    Returns:
    - Scaled and centered image.
    """
    # Crop the image to remove the bleed
    left = x_crop
    right = img.width - x_crop
    top = y_crop
    bottom = img.height - y_crop
    cropped_img = img.crop((left, top, right, bottom))
    img = cropped_img

    original_width, original_height = img.size
    target_width, target_height = card_size_pixels

    # Determine the scale factor while maintaining the aspect ratio
    scale_factor = min(target_height / original_height, target_width / original_width)
    
    # Calculate the new size after scaling
    new_size = (int(original_width * scale_factor), int(original_height * scale_factor))
    scaled_img = img.resize(new_size, Image.LANCZOS)

    # If the scaled image is smaller than the target in either dimension, center it
    x_offset = max(0, (target_width - new_size[0]) // 2)
    y_offset = max(0, (target_height - new_size[1]) // 2)

    # Create a new image with white background to fill the card size
    new_img = Image.new('RGB', card_size_pixels, "white")
    # Paste the scaled image onto the center of the new image
    new_img.paste(scaled_img, (x_offset, y_offset))

    return new_img

def resize_images(image_files, directory, card_size):
    """
    Yields resized images from a list of image filenames.

    Args:
    - image_files: List of filenames.
    - directory: Path to the image files.
    - card_size: Tuple (width, height) to resize images to.
    """
    for filename in tqdm(image_files, desc="Resizing images"):
        with Image.open(os.path.join(directory, filename)) as img:
            yield scale_image_to_card(img, card_size)

def draw_grid(pdf, num_rows, num_cols, cell_width, cell_height, x_margin, y_margin, page_size, bleed=10):
    """
    Draws a grid on the PDF page to separate cards using FPDF.

    Args:
    - pdf: FPDF object for drawing on the PDF.
    - num_rows, num_cols: Grid dimensions.
    - cell_width, cell_height: Dimensions of each grid cell.
    - x_margin, y_margin: Margins from the edges of the page.
    - page_size: Size of the PDF page.
    """
    pdf.set_draw_color(0, 0, 0)  # set color to black
    x_bleed, y_bleed = x_margin - bleed, y_margin - bleed
    # Draw horizontal lines
    for row in range(num_rows + 1):
        y = row * cell_height + y_margin
        pdf.line(x_bleed, y, page_size[0] - x_bleed, y)

    # Draw vertical lines
    for col in range(num_cols + 1):
        x = col * cell_width + x_margin
        pdf.line(x, y_bleed, x, page_size[1] - y_bleed)

def draw_grid2(draw, num_rows, num_cols, cell_width, cell_height, x_margin, y_margin, page_size, bleed=10):
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

def create_pdf_with_fpdf(images, page_size, grid_size, card_size, output_pdf):
    """
    Creates a PDF file from a list of images, placing them in a grid using FPDF.
    This version places images without gaps between them for easy cutting.

    Args:
    - images: List of PIL Image objects.
    - page_size: Size of the PDF page (width, height).
    - grid_size: Grid size as (num_cols, num_rows).
    - card_size: Size of individual cards (width, height) in points.
    - output_pdf: Output PDF file path.
    """
    pdf = FPDF(unit="pt", format=page_size)
    images_per_page = grid_size[0] * grid_size[1]
    
    # Calculate the total width and height used by all the cards on the page
    total_width = card_size[0] * grid_size[0]
    total_height = card_size[1] * grid_size[1]
    
    # Calculate margins based on the remaining space, divided by 2 for equal margins on both sides
    x_margin = (page_size[0] - total_width) / 2
    y_margin = (page_size[1] - total_height) / 2

    for page in tqdm(range(0, len(images), images_per_page), desc="Creating PDF pages"):
        pdf.add_page()
        # Draw the grid
        draw_grid(pdf, grid_size[1], grid_size[0], card_size[0], card_size[1], x_margin, y_margin, page_size)
        
        for idx in range(images_per_page):
            if page + idx >= len(images): break
            image = images[page + idx]
            row, col = divmod(idx, grid_size[0])
            x_offset = col * card_size[0] + x_margin
            y_offset = row * card_size[1] + y_margin
            
            temp_image_path = f"temp_page_{page}_{idx}.png"
            image.save(temp_image_path, 'PNG')

            pdf.image(temp_image_path, x=x_offset, y=y_offset, w=card_size[0], h=card_size[1])
            os.remove(temp_image_path)
        
    pdf.output(output_pdf)

def main():
    IMAGE_DIR = "all_files"
    SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
    OUTPUT_PDF = os.path.join(SCRIPT_DIR, "mysterious_cyclones_full.pdf")
    PAGE_SIZE = (595, 842)  # A4 in points
    GRID_SIZE = (3, 3)  # 3x3 grid
    CARD_SIZE = (mm_to_points(63), mm_to_points(88))

    mm_width, mm_height = 63, 88  # Card dimensions in millimeters
    inch_width, inch_height = mm_width / 25.4, mm_height / 25.4  # Convert mm to inches
    dpi = 300
    pixel_width, pixel_height = int(inch_width * dpi), int(inch_height * dpi)  # Convert to pixels
    

    print("Step 1: Reading PNG Files")
    image_files = read_png_files(IMAGE_DIR)[:81]

    print("Step 2: Resizing Images")
    CARD_SIZE = (pixel_width, pixel_height)
    resized_images = list(resize_images(image_files, IMAGE_DIR, CARD_SIZE))

    print("Step 3: Creating PDF")
    #create_pdf(resized_images, PAGE_SIZE, GRID_SIZE, CARD_SIZE, OUTPUT_PDF)
    # Convert card size to points for PDF placement
    card_size_points = (mm_to_points(mm_width), mm_to_points(mm_height))
    create_pdf_with_fpdf(resized_images, PAGE_SIZE, GRID_SIZE, card_size_points, OUTPUT_PDF)

    print("Completed. PDF saved as:", OUTPUT_PDF)

if __name__ == "__main__":
    main()