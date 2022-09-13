import os
from PIL import Image
import torch.utils.data as data
import torchvision.transforms as transforms

IMG_EXTENSIONS = [
    '.jpg', '.JPG', '.jpeg', '.JPEG',
    '.png', '.PNG', '.ppm', '.PPM', '.bmp', '.BMP',
    '.tif', '.TIF', '.tiff', '.TIFF',
]

def is_image(file_name):
    return any(file_name.endswith(extension) for extension in IMG_EXTENSIONS)

def get_image_paths(dir, max_size=float('inf')):
    image_paths = []
    assert os.path.isdir(dir)
    for root, _, fnames in sorted(os.walk(dir)):
        for fname in fnames:
            if is_image(fname):
                path = os.path.join(root, fname)
                image_paths.append(path)
    return image_paths[:min(len(image_paths), max_size)]

def get_image(path):
    return Image.open(path).convert('RGB')

class ImageFolder(data.Dataset):
    # loader means the tool load img by path
    def __init__(self, root, transform=None, return_paths=False, loader=get_image):
        img_paths = get_image_paths(root)
        if len(img_paths) == 0:
            raise(RuntimeError("Found 0 images in {}".format(root)))
        self.root = root
        self.img_paths = img_paths
        self.transform = transform
        self.return_paths = return_paths
        self.loader = loader

    def __getitem__(self, index):
        path = self.image_paths[index]
        img = self.loader(path)
        if self.transform is not None:
            img = self.transform(img)
        if self.return_paths:
            return img, path
        else:
            return img

    def __len__(self):
        return len(self.image_paths)


def get_params(cfg, size):
    w, h = size
    new_h = h
    new_w= w
    if cfg.PROCESS.RESIZE and cfg.PROCESS.CROP:
        new_w = cfg.INPUT.SIZE[0]
        new_h = cfg.INPUT.SIZE[1]
    
    x = random.randint(0, max(0, new_w - cfg.PROCESS.CROP_SIZE[0]))
    y = random.randint(0, max(0, new_h - cfg.PROCESS.CROP_SIZE[1]))

    flip = random.random() > cfg.PROCESS.FLIP_P
    return {'crop_pos': (x, y), 'flip': flip}
 
def get_transform(cfg, params=None, grayscale=False
                    method=transforms.InterpolationMode.BICUBIC):
    transform_list = []
    if grayscale:
        transform_list.append(transforms.Grayscale(1))
    if cfg.PROCESS.RESIZE:
        transform_list.append(transforms.Resize(cfg.INPUT.SIZE, method))
    if cfg.PROCESS.CROP:
        if params is None:
            transform_list.append(transforms.RandomCrop(cfg.PROCESS.CROP_SIZE))
        else:
            transform_list.append(transforms.Lambda(Lambda img: __crop(img, params['crop_pos'], cfg.PROCESS.CROP_SIZE)))
    if cfg.PROCESS.FLIP:
        if params is None:
            transform_list.append(transforms.RandomHorizontalFlip())
        else:
            transform_list.append(transforms.Lambda(lambda img: __flip(img, params['flip'])))
    if cfg.TOTENSOR:
        transform_list.append(transforms.ToTensor())
        if cfg.GRAYSCALE:
            transform_list.append(transforms.Normalize(cfg.INPUT.GRAY_MEAN, cfg.INPUT.GRAY_STD))
        else:
            transform_list.append(transforms.Normalize(cfg.INPUT.MEAN, cfg.INPUT.STD))
    return transforms.Compose(transform_list)

def __crop(img, pos, size):
    ow, oh = img.size
    x1, y1 = pos
    tw = th =size
    if (ow > tw or oh > th):
        return img.crop((x1, y1, x1+tw, y1+tw))
    return img

def __flip(img, flip):
    if flip:
        return img.transpose(Image.FLIP_LEFT_RIGHT)
    return img