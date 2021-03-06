from validation.pipeline.validation_task import PredictorTask
import config as fire3_config
import scipy
import os

os.environ['GLOG_minloglevel'] = '3' 
import caffe
caffe.set_mode_gpu()
import numpy as np

IMG_DTYPE = np.float
SEG_DTYPE = np.uint8


def to_scale(img, shape=None):
	if shape is None:
		shape = fire3_config.slice_shape

	height, width = shape
	if img.dtype == SEG_DTYPE:
		return scipy.misc.imresize(img,(height,width),interp="nearest").astype(SEG_DTYPE)
	elif img.dtype == IMG_DTYPE:
		max_ = np.max(img)
		factor = 256.0/max_ if max_ != 0 else 1
		return (scipy.misc.imresize(img,(height,width),interp="nearest")/factor).astype(IMG_DTYPE)
	else:
		raise TypeError('Error. To scale the image array, its type must be np.uint8 or np.float64. (' + str(img.dtype) + ')')


def zoomliver_UNET_processor(img, seg):
	""" Custom preprocessing of img,seg for UNET architecture:
	Crops the background and upsamples the found patch."""

	# Remove background !
	img = np.multiply(img,np.clip(seg,0,1))
	# get patch size
	col_maxes = np.max(seg, axis=0) # a row
	row_maxes = np.max(seg, axis=1)# a column

	nonzero_colmaxes = np.nonzero(col_maxes)[0]
	nonzero_rowmaxes = np.nonzero(row_maxes)[0]

	x1, x2 = nonzero_colmaxes[0], nonzero_colmaxes[-1]
	y1, y2 = nonzero_rowmaxes[0], nonzero_rowmaxes[-1]
	width = x2-x1
	height= y2-y1
	MIN_WIDTH = 60
	MIN_HEIGHT= 60
	x_pad = (MIN_WIDTH - width) / 2 if width < MIN_WIDTH else 0
	y_pad = (MIN_HEIGHT - height)/2 if height < MIN_HEIGHT else 0

	x1 = max(0, x1-x_pad)
	x2 = min(img.shape[1], x2+x_pad)
	y1 = max(0, y1-y_pad)
	y2 = min(img.shape[0], y2+y_pad)

	img = img[y1:y2+1, x1:x2+1]
	seg = seg[y1:y2+1, x1:x2+1]

	img = to_scale(img, (388,388))
	seg = to_scale(seg, (388,388))
	# All non-lesion is background
	seg[seg==1]=0
	#Lesion label becomes 1
	seg[seg==2]=1

	# Now do padding for UNET, which takes 572x572
	#seg=np.pad(seg,((92,92),(92,92)),mode='reflect')
	img=np.pad(img,92,mode='reflect')
	return img, (x1,x2,y1,y2)



class fire3Predictor(PredictorTask):


	def __init__(self, fold=1):
		self.net=caffe.Net(fire3_config.deployprototxt[fold-1],fire3_config.models[fold-1],caffe.TEST)
		self.fold = fold
		self.cascade = 1

		self.last_prob_volume = None
		self.last_nifti_path = None

	def run(self, fileidx_niftipath_imgvol):

		file_index, nifti_path, imgvol_downscaled = fileidx_niftipath_imgvol

		#the raw probabilites of step 1
		probvol = np.zeros((fire3_config.slice_shape[0],fire3_config.slice_shape[1],imgvol_downscaled.shape[2],3))

		print "Running Step 1"
		
		for i in range(imgvol_downscaled.shape[2]):
			slc = imgvol_downscaled[:,:,i]
			#create mirrored slc for unet
			slc = np.pad(slc,((92,92),(92,92)),mode='reflect')

			#load slc into network and do forward pass
			self.net.blobs['data'].data[...] = slc
			self.net.forward()

			#now save raw probabilities
			probvol[:,:,i,:]  = self.net.blobs['prob'].data.transpose((0,2,3,1))[0]

			#result shape is batch_img_idx , height, width, probability_of_class
			
		self.last_prob_volume = probvol
		self.last_nifti_path = nifti_path
		return [file_index, nifti_path, np.argmax(probvol, axis=3)]



	def save(self, directory):
		basename = os.path.basename(self.last_nifti_path)
		if basename.endswith('.nii'):
			basename = basename[:-4]
		basename += ".npy"
		
		foldername = os.path.dirname(self.last_nifti_path)
		OUTDIR = "plainunet_validation_result"
		OUTDIR = os.path.join(foldername, OUTDIR)
		
		if not os.path.exists(OUTDIR):
			os.makedirs(OUTDIR)
			
		out_filename = os.path.join(OUTDIR, basename)
		
		print "Saving prediction to ",out_filename
		np.save(out_filename, self.last_prob_volume)
		
		
		
		
		
