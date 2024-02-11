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
                size='1024x1792'
            )
            break
        except:
            print(f"{str(datetime.datetime.now())} - Attempt {attempt+1} of {i_range} failed to generate image for {media_object['title']}, ID: {media_object['id']}.")
    else:
        return False

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
    except:
        print(f"Error saving image {media_object['id']}.png")
        return False, "FAILED"
    
    return True, file_path

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
        
        #https://stackoverflow.com/questions/4902198/pil-how-to-scale-text-size-in-relation-to-the-size-of-the-image
        W, H = img.size

        draw = ImageDraw.Draw(img)

        text = media_object["title"]

        fontsize = 1  # starting font size

        # portion of image width you want text width to be
        img_fraction = 0.95

        font = ImageFont.truetype(font_path, fontsize)
      
        while font.getlength(text) < img_fraction*W:
            # iterate until the text size is just larger than the criteria
            fontsize += 1
            font = ImageFont.truetype(font_path, fontsize)

        # optionally de-increment to be sure it is less than criteria
        fontsize -= 1
        font = ImageFont.truetype(font_path, fontsize)
        
        w = font.getlength(text)
        w_placement=(W-w)/2
        draw.text((w_placement, 50), text, font=font, stroke_width=2, stroke_fill='black') # put the text on the image


        draw = ImageDraw.Draw(img)
        text = media_object["tagline"]
        fontsize = 1  # starting font size

        # portion of image width you want text width to be
        img_fraction = 0.90

        font = ImageFont.truetype(font_path, fontsize)
        while font.getlength(text) < img_fraction*W:
            # iterate until the text size is just larger than the criteria
            fontsize += 1
            font = ImageFont.truetype(font_path, fontsize)

        # optionally de-increment to be sure it is less than criteria
        fontsize -= 3
        font = ImageFont.truetype(font_path, fontsize)

        w = font.getlength(text)
        w_placement=(W-w)/2
        draw.text((w_placement, H - 150), text, font=font, stroke_width=1, stroke_fill='black') # put the text on the image

        img = img.resize((724, 1267))
        img = img.convert('RGB')
        img.save(image_path.replace('png', 'jpg'), 'JPEG', quality=40)

    #Delete the original png file
    os.remove(image_path)


def formatText(text, type, img):
    print("here")


def main():

    processed_count=0
    created_count=0

    for root, dirs, files in os.walk(objects_directory):
        for filename in files:
            # Full path to the file
            file_path = os.path.join(root, filename)

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
args = parser.parse_args()




imageBuildList(os.getcwd() + "/outputs/media/generated/")
# Run the main loop
main()