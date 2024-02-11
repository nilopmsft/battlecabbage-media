from openai import AzureOpenAI
from dotenv import load_dotenv
import os
import requests
from PIL import Image, ImageDraw, ImageFont
from matplotlib import font_manager
import json
import random
from fontTools.ttLib import TTFont, TTCollection
import argparse
import datetime


# REQUIREMENTS
# pip install matplotlib
# pip install python-dotenv
# pip install openai
# pip install pillow

load_dotenv()

# TODO:
# 2. Implement the ability to generate a response without saving it to a file, dry run
# 3. Implement checks for failures and move forward. If a failure occurs, log the prompt and response to a file for review, potenitally retrying the prompt a few times before moving on.
# 4. Ability to break up text into multine and format it for the poster.
# 5. Ability to add a logo to the poster like the rating
# 6. Format the font to have better readability. Maybe on complimentary color, outlines, etc.
# 7. Proper checks if certain values came back from completion, example critic_score
# 8. Check for letterbox image and regenerate, Cameron?
# 9. Fix lq flag to work properly, keeps failing size, I blame Dalle3, works with 1024x1024 not 512x512


# Check if the image has already been generated
def checkImage(images_directory,image_id):
    if os.path.isfile(images_directory + image_id + ".jpg"):
        return True
    else:
        return False

def imageBuildList(media_directory):

    json_files = []
    jpg_files = []
    png_files = []
    # Iterate over all subdirectories in main generated media directory
    for root, dirs, files in os.walk(media_directory):
        json_files += [os.path.join(root, f) for f in files if f.endswith('.json')]
        jpg_files += [os.path.join(root, f) for f in files if f.endswith('.jpg')]
        png_files += [os.path.join(root, f) for f in files if f.endswith('.png')]

    # Check if there is a .jpg file that matches the same name as a .json file
    missing_images = []
    for json_file in json_files:
        # Remove the file extension to get the base name
        base_name = os.path.splitext(json_file)[0]
        if base_name + '.jpg' not in jpg_files:
            #missing_images.append(f"{root}/{base_name}.json")
            missing_images.append(f"{base_name}.json")
    
    return missing_images, png_files      


# Generate the prompt for the image based upon the media object info
def generateImagePrompt(media_object):
    
    # Create the AzureOpenAI client for image prompt
    client = AzureOpenAI(
        api_key=os.getenv("AZURE_OPENAI_COMPLETION_ENDPOINT_KEY"),  
        api_version=os.getenv("AZURE_OPENAI_COMPLETION_API_VERSION"),
        azure_endpoint = os.getenv("AZURE_OPENAI_COMPLETION_ENDPOINT")
    )
    deployment_name=os.getenv("AZURE_OPENAI_COMPLETION_DEPLOYMENT_NAME")
    
    # Get a list of all font files
    font_files = font_manager.findSystemFonts(fontpaths=None, fontext='ttf')

    # Get a list of all font names
    font_names = []
    for font_file in font_files:
        try:
            # Try to open as a single font file
            font = TTFont(font_file)
            font_names.append(font['name'].getDebugName(1))
        except:
            # If that fails, try to open as a font collection file
            font_collection = TTCollection(font_file)
            for font in font_collection.fonts:
                font_names.append(font['name'].getDebugName(1))

    # trim the list to 25 random fonts
    if len(font_names) > 50:
        font_names = random.sample(font_names, 50)  

    # TODO: Add error handling for failed requests
    # Send the description to the API
    with open(templates_base + "prompts.json") as json_file:

        prompt_json=json.load(json_file)
        prompt_image_json=random.choice(prompt_json["prompts_image"])
    
        #remove objects from media_object that are not needed for the prompt

        object_keys_keep = ["title", "tagline", "mpaa_rating", "description"]
        media_object ={k: media_object[k] for k in object_keys_keep}
        media_object=json.dumps(media_object)

        full_prompt = prompt_image_json + json.dumps(media_object) + ",{'font_names':" + json.dumps(font_names)
        if args.verbose: print(f"{str(datetime.datetime.now())} -  Prompt\n" + full_prompt)
        response = client.chat.completions.create(model=deployment_name, messages=[{"role": "user", "content":full_prompt}], max_tokens=500, temperature=0.7)
        completion=response.choices[0].message.content

        # Find the start and end index of the json object
        start_index = completion.find("{")
        end_index = completion.find("}")
        completion = json.loads(completion[start_index:end_index+1])
        
        if args.verbose: print(f"{str(datetime.datetime.now())} - Completion \n {json.dumps(completion, indent=4)}")

        return completion
    

# Generate the image using the prompt
def generateImage(file_path, image_prompt, media_object):

    client = AzureOpenAI(
        api_version=os.getenv("AZURE_OPENAI_DALLE3_API_VERSION"),  
        api_key=os.getenv("AZURE_OPENAI_DALLE3_ENDPOINT_KEY"),
        azure_endpoint=os.getenv("AZURE_OPENAI_DALLE3_ENDPOINT")
    )

    i_range = 5
    for attempt in range(i_range):
        try:
            result = client.images.generate(
                model=os.getenv("AZURE_OPENAI_DALLE3_DEPLOYMENT_NAME"), # the name of your DALL-E 3 deployment
                prompt=image_prompt["image_prompt"],
                n=1,
                size="1024x1024" if args.low_quality else "1024x1792"
            )
            break
        except Exception as e:
            print(f"{str(datetime.datetime.now())} - Attempt {attempt+1} of {i_range} failed to generate image for {media_object['title']}, ID: {media_object['id']}.")
            print(f"Error: {e}")
    else:
        return False, "FAILED"

    # Grab the first image from the response
    json_response = json.loads(result.model_dump_json())

    # Initialize the image path (note the filetype should be png)
    #image_path = os.path.join(images_directory, media_object["id"] +'.png')

    # Retrieve the generated image and save it to the images directory
    image_url = json_response["data"][0]["url"]  # extract image URL from response
    generated_image = requests.get(image_url).content  # download the image
    
    file_path=file_path.replace('.json','.png')
    try:
        with open(file_path, "wb") as image_file:
            image_file.write(generated_image)
            return True, file_path
    except:
        print(f"Error saving image {media_object['id']}.png")
        return False, "FAILED"
    

# Add various text to the image and resize
def processImage(completion, media_object, image_path):

    #image=images_directory + "/" + media_object["id"] + ".png"

    # Get a list of all font files
    font_files = font_manager.findSystemFonts(fontpaths=None, fontext='ttf')

    # The name of the font you're looking for
    font_name_to_find = completion["font"]

    # Get the path of the font
    font_path = None
    for font_file in font_files:
        try:
            # Try to open as a single font file
            font = TTFont(font_file)
            if font['name'].getDebugName(1) == font_name_to_find:
                font_path = font_file
                break
        except:
            # If that fails, try to open as a font collection file
            font_collection = TTCollection(font_file)
            for font in font_collection.fonts:
                if font['name'].getDebugName(1) == font_name_to_find:
                    font_path = font_file
                    break

    if font_path is None:
        font_path="arial.ttf"

    # Open an image file for manipulation
    with Image.open(image_path) as img:
        
        img_w, img_h = img.size

        draw = ImageDraw.Draw(img)

        img = writeText(
            media_object["title"],
            ":",
            0.96,
            font_path,
            img_w,
            1,
            25,
            20, 
            2,
            img
        )

        # Write Tagline, this is currently multi-line friendly
        img = writeText(
            media_object["tagline"],
            ",",
            0.80,
            font_path,
            img_w,
            7,
            img_h - 280,
            30,
            1,
            img
        )

        if not args.low_quality:
            img = img.resize((724, 1267))
            img = img.convert('RGB')
            img.save(image_path.replace('png', 'jpg'), 'JPEG', quality=70)
            #Delete the original png file
            os.remove(image_path)
        else:
            img.save(image_path, 'PNG')

    return True

# TODO rewrite this later to take in a list of options from a template file, not all current options  would be in template.
# TODO calculate the offset by number of lines. Likely have to pass in image height and just the offset, not calculated version.
def writeText(
        text_string, # The text to write
        delimiter, # The delimiter to split the text on
        img_fraction, # The fraction of the image width the text should take up
        font_path, # The path to the font file
        img_w, # The width of the image
        decrement, # The amount to decrement the font size by
        placement_offset, # Where to start from top of image
        line_padding, # The amount of padding between lines
        stroke_width, # The width of the stroke
        img # The draw object
    ):
    
    draw = ImageDraw.Draw(img)

    # split the string on a delimeter into a list and find the biggest portion, keep the delimiter
    text_list = text_string.split(delimiter)
    max_text = max(text_list, key=len)
    text_list[0] += delimiter

    fontsize = 1  # starting font size
    font = ImageFont.truetype(font_path, fontsize)

    # Find  font size to fit the text based upon fraction of the image width and biggest string section
    while font.getlength(max_text) < img_fraction*img_w:
        # iterate until the text size is just larger than the criteria
        fontsize += 1
        font = ImageFont.truetype(font_path, fontsize)
    
    # Decrement to be sure it is less than criteria and styled
    fontsize -= decrement
    font = ImageFont.truetype(font_path, fontsize)
    #placement_w = font.getlength(max_text)

    #return font, placement_w

    # TODO FIGURE OUT THE HORIZONTAL PLACEMENT ON BOTTOM TEXT
    # text_count = 1
    # for text_line in text_list:
    #     print(text_line)
    #     # remove proceeding and trailing spaces
    #     text_line = text_line.strip()
    #     w = font.getlength(text_line)
    #     w_placement=(img_w-w)/2
    #     # Get the font's ascent and descent
    #     ascent, descent = font.getmetrics()
    #     # The height of the font is the sum of its ascent and descent
    #     font_height = ascent + descent
    #     if text_count == 1:
    #         h_placement = placement_offset
    #     else:
    #         h_placement = placement_offset + ((font_height + 10) * text_count)
    #     draw.text((w_placement, h_placement), text_line, font=font, stroke_width=stroke_width, stroke_fill='black') # put the text on the image
        
    #     text_count += 1

    w = font.getlength(max_text)
    w_placement=(img_w-w)/2
    text_count = 1
    for text_line in text_list:
        #print(text_line)
        # remove proceeding and trailing spaces
        text_line = text_line.strip()
        # w = font.getlength(text_line)
        # w_placement=(img_w-w)/2
        # Get the font's ascent and descent
        ascent, descent = font.getmetrics()
        # The height of the font is the sum of its ascent and descent
        font_height = ascent - descent
        # print(f"Ascent: {ascent}, Descent: {descent}")
        # print (f"Font Height: {font_height}")
        y_placement = placement_offset + ((font_height) * (text_count - 1))
        if text_count > 1:
            y_placement = y_placement + (line_padding * (text_count - 1))
        # if text_count == 1:
        #     y_placement = placement_offset
        # elif text_count == 2:
        #     y_placement = placement_offset + ((font_height) * text_count)
        print(f"Text: {text_line}, Line: {text_count}, Font Height:, {font_height}  Y Placement: {y_placement}, Start Offset: {placement_offset}")
        draw.text((w_placement, y_placement), text_line, font=font, stroke_width=stroke_width, stroke_fill='black') # put the text on the image
        
        text_count += 1
    
    # print("here")
    # exit()
    return img

def main():

    processed_count=0
    created_count=0

    # for root, dirs, files in os.walk(objects_directory):
    #     for filename in files:
    #         # Full path to the file
    #         file_path = os.path.join(root, filename)

    # Get list of all media objects missing a poster, and orphaned png posters files    
    missing_list, png_list = imageBuildList(os.getcwd() + "/outputs/media/generated/")

    if len(png_list) > 0:
        print(f"{str(datetime.datetime.now())} - Orphaned PNG files found, quick housekeeping.")
        for png_file in png_list:
            os.remove(png_file)

    missing_count = len(missing_list)

    if missing_count > 0:
        print(f"{str(datetime.datetime.now())} - Starting Media Image generation, Total Missing: {missing_count}")
        for filepath in missing_list:

            if args.single and processed_count > 0: 
                print(f"{str(datetime.datetime.now())} - Single image processing mode enabled, skipping additional media objects.")
                exit()

            with open(filepath, 'r') as file:
                media_object = json.load(file)
                    
                if args.verbose: print(f"{str(datetime.datetime.now())} - Generating Image Prompt for {media_object["title"]}, ID: {media_object["id"]}")
                completion=generateImagePrompt(media_object)
                if args.verbose: print(f"{str(datetime.datetime.now())} - Image Prompt Generated for {media_object["title"]}, ID: {media_object["id"]} \nImage Prompt:\n{completion["image_prompt"]}")
                                                    
                if args.verbose: print(f"{str(datetime.datetime.now())} - Generating Image for {media_object["title"]}, ID: {media_object["id"]}")
                result, image_path = generateImage(filepath, completion, media_object)
                if result == True:
                    processImage(completion, media_object, image_path)
                    print(f"{str(datetime.datetime.now())} - Image created for {media_object["title"]} \nLocation: {str(image_path.replace('.png','.jpg'))}")
                    created_count+=1
                else:
                    print(f"{str(datetime.datetime.now())} - Failed to generate image for {media_object["title"]} ID: {media_object["id"]}")
                
                processed_count+=1
        message = f"{str(datetime.datetime.now())} - All media objects reviewed."
        if processed_count > 0: 
            message += f" Image Create Count: {str(created_count)}, Processed Count: {str(processed_count)}"
            print(message)
    else:
        print(f"{str(datetime.datetime.now())} - No media objects missing images.")


load_dotenv()
working_dir=os.getcwd()
objects_directory = working_dir + "/outputs/media/objects/"
images_directory = working_dir + "/outputs/media/images/"
templates_base = working_dir + "/library-management/templates/"
outputs_dir = "outputs/media/"

# For command line arguments
parser = argparse.ArgumentParser(description="Provide various run commands.")
# Argument for the count of media objects to generate
parser.add_argument("-c", "--count", help="Number of media objects to generate")
# Argument for the dry run, to generate a response without saving it to a file
parser.add_argument("-d", "--dryrun", action='store_true', help="Dry run, generate a response without saving it to a file")
# Argument for verbose mode, to display object outputs
parser.add_argument("-v", "--verbose", action='store_true', help="Show object outputs like prompts and completions")
parser.add_argument("-s", "--single", action='store_true', help="Only process a single image, for testing purposes")
parser.add_argument("-lq", "--low_quality", action='store_true', help="Create low quality images for testing.")
args = parser.parse_args()




imageBuildList(os.getcwd() + "/outputs/media/generated/")
# Run the main loop
main()