import random
import torch

class ImagePool():
    """This class implements an image buffer that stores previously generated images.

    This buffer enables us to update discriminators using a history of generated images probabilisticly
    rather than the ones produced by the latest generators.
    """

    def __init__(self, pool_size):
        self.pool_size = pool_size
        assert(self.pool_size > 0)
        self.num_imgs = 0
        self.images = []
    
    def query(self, images):
        """Return an image from the pool.

        Parameters:
            images: the latest generated images from the generator

        Returns images from the buffer.

        By 50%, the buffer will return images previously stored in the buffer,
        By another 50%, the buffer will return input images.

        and insert the current images to the buffer.
        """
        if self.pool_size == 0:
            return images
        # print(images.shape)
        return_images = []
        for image in images:
            image = torch.unsqueeze(image.data, 0)
            if self.num_imgs < self.pool_size:
                self.num_imgs += 1
                self.images.append(image)
                return_images.append(image)
            else:
                p = random.uniform(0, 1)
                if p > 0.5:
                    # id 属于 [0, num_images - 1]
                    random_id = random.randint(0, self.num_imgs - 1)
                    tmp = self.images[random_id].clone()
                    self.images[random_id] = image
                    return_images.append(tmp)
                else:
                    return_images.append(image)
        return_images = torch.cat(return_images, 0)
        return return_images