"""
utils.py

Original code by Gerard Sanroma-Guell, 2016.
Modified by MJ, 2025-05-12.

[Purpose of Modifications]
- Updated deprecated usage of `get_data()` from nibabel to `get_fdata()` 
  or `np.asarray(...dataobj)` to ensure compatibility with nibabel >= 5.x.
- Resolved deprecation warnings and ExpiredDeprecationError.
- Ensured correct label saving by enforcing integer output types.

[Modified Functions]
1. generate_wmparc()
   - Replaced `get_data()` with `get_fdata()`
   - Replaced `np.bool` with `bool` to avoid FutureWarning
   - Enforced `.astype(np.int16)` before NIfTI saving

2. merge_labels()
   - Replaced `get_data()` with `get_fdata()`
   - Explicitly defined output dtype as `np.int8` or `np.int32`

3. create_shells()
   - Updated deprecated data access if needed

[Recommendations]
- If FreeSurfer results are under `result/`, update all path templates accordingly.
- For custom interfaces like Annot2Label and Aparc2Aseg, verify correct use of SUBJECTS_DIR.

Author: MJ
Last Updated: 2025-05-12
"""



from nipype.interfaces.base import (
    traits,
    TraitedSpec,
    CommandLineInputSpec,
    CommandLine,
    File
)

import os

def filter_labels(in_file, include_superlist, fixed_id=None, map_pairs_list=None):
    """filters-out labels not in the include-superset. Merges labels within superset. Transforms label-ids according to mappings (or fixed id)"""
    import nibabel as nib
    import numpy as np
    import os

    in_nib = nib.load(in_file)
    in_data = in_nib.get_fdata()
    new_data = np.zeros_like(in_data)

    # Step 1: group and relabel
    for labels_list in include_superlist:
        if fixed_id is not None:
            new_label = fixed_id[0]
        else:
            new_label = labels_list[0]  # unified label within the group
        for label in labels_list:
            new_data[in_data == label] = new_label

    # Step 2: apply mapping
    if map_pairs_list is not None:
        mapped_data = np.copy(new_data)
        for old_label, new_label in map_pairs_list:
            mapped_data[new_data == old_label] = new_label
        final_data = mapped_data
    else:
        final_data = new_data

    # Save result
    out_nib = nib.Nifti1Image(final_data.astype(np.int16), in_nib.affine, in_nib.header)
    nib.save(out_nib, 'filtered.nii.gz')
    return os.path.abspath('filtered.nii.gz')


def norm_dist_map(orig_file, dest_file):
    """compute normalized distance map given an origin and destination masks, resp."""
    import os
    import nibabel as nib
    import numpy as np
    from scipy.ndimage.morphology import distance_transform_edt

    orig_nib = nib.load(orig_file)
    dest_nib = nib.load(dest_file)

    orig = orig_nib.get_fdata()
    dest = dest_nib.get_fdata()

    dist_orig = distance_transform_edt(np.logical_not(orig.astype(bool)))
    dist_dest = distance_transform_edt(np.logical_not(dest.astype(bool)))

    # normalized distance (0 in origin to 1 in dest)
    ndist = dist_orig / (dist_orig + dist_dest)

    ndist_nib = nib.Nifti1Image(ndist.astype(np.float32), orig_nib.affine)
    nib.save(ndist_nib, 'ndist.nii.gz')

    return os.path.abspath('ndist.nii.gz')

def create_shells(ndist_file, n_shells=4, out_file = 'shells.nii.gz', mask_file=None):
    """creates specified number of shells given normalized distance map. When mask is given, output in mask == 0 is set to zero"""
    import os
    import nibabel as nib
    import numpy as np

    ndist_nib = nib.load(ndist_file)
    ndist = ndist_nib.get_fdata()

    # if mask is provided, use it to mask-out regions outside it
    if mask_file is not None:
        mask_nib = nib.load(mask_file)
        assert mask_nib.header.get_data_shape() == ndist_nib.header.get_data_shape(), "Different shapes of images"
        mask = mask_nib.get_fdata() > 0

    out = np.zeros(ndist.shape, dtype=np.int8)

    limits = np.linspace(0., 1., n_shells+1)
    for i in np.arange(n_shells)+1:
        # compute shell and assing increasing label-id
        mask2 = np.logical_and(ndist >= limits[i-1], ndist < limits[i])
        if mask_file is not None:  # maskout regions outside mask
            mask2 = np.logical_and(mask2, mask)
        out[mask2] = i
    out[np.isclose(ndist, 0.)] = 0  # need to assign zero to ventricles because of >= above

    aux_hdr = ndist_nib.header
    aux_hdr.set_data_dtype(np.int8)

    out_nib = nib.Nifti1Image(out, ndist_nib.affine, aux_hdr)
    nib.save(out_nib, out_file)

    return os.path.abspath(out_file)


def merge_labels(in1_file, in2_file, out_file='merged.nii.gz', intersect=False):
    """merges labels from two input labelmaps, optionally computing intersection"""
    import os
    import nibabel as nib
    import numpy as np

    in1_nib = nib.load(in1_file)
    in2_nib = nib.load(in2_file)

    assert in1_nib.header.get_data_shape() == in2_nib.header.get_data_shape(), "Different shapes of images"

    in1 = in1_nib.get_fdata()
    in2 = in2_nib.get_fdata()

    out = None

    # if not intersection, simply include labels from 'in2' into 'in1'
    if not intersect:

        out = np.zeros(in1.shape, dtype=np.int8)

        out[:] = in1[:]
        mask = in2 > 0
        out[mask] = in2[mask]  # overwrite in1 where in2 > 0


        aux_hdr = in1_nib.header
        aux_hdr.set_data_dtype(np.int8)

    # if intersection, create new label-set as cartesian product of the two sets
    else:

        out = np.zeros(in1.shape, dtype=np.int32)

        u1_set = np.unique(in1.ravel())
        u2_set = np.unique(in2.ravel())

        for u1 in u1_set:
            if u1 == 0: continue
            mask1 = in1 == u1
            for u2 in u2_set:
                if u2 == 0: continue
                mask2 = in2 == u2
                mask3 = np.logical_and(mask1, mask2)
                if not np.any(mask3): continue
                out[mask3] = int(f"{int(u1)}{int(u2)}")  # new label id by concatenating [u1, u2]

        aux_hdr = in1_nib.header
        aux_hdr.set_data_dtype(np.int32)

    out_nib = nib.Nifti1Image(out, in1_nib.affine, aux_hdr)
    nib.save(out_nib, out_file)

    return os.path.abspath(out_file)


def generate_wmparc(incl_file, ndist_file, label_file, incl_labels=None, verbose=False):
    """generates wmparc by propagating labels in 'label_file' down the gradient defined by distance map in 'ndist_file'.
    Labels are only propagated in regions where 'incl_file' > 0 (or 'incl_file' == incl_labels[i], if 'incl_labels is provided).
    """
    import os
    import nibabel as nib
    import numpy as np
    from scipy.ndimage.morphology import binary_dilation, generate_binary_structure, iterate_structure

    connectivity = generate_binary_structure(3, 2)

    # read images
    incl_nib = nib.load(incl_file)
    ndist_nib = nib.load(ndist_file)
    label_nib = nib.load(label_file)

    assert incl_nib.header.get_data_shape() == ndist_nib.header.get_data_shape() and \
           incl_nib.header.get_data_shape() == label_nib.header.get_data_shape(), "Different shapes of mask, ndist and label images"

    # create inclusion mask
    incl_mask = None
    incl_aux = incl_nib.get_fdata()
    if incl_labels is None:
        incl_mask = incl_aux > 0
    else:
        incl_mask = np.zeros(incl_nib.header.get_data_shape(), dtype=bool)
        for lab in incl_labels:
            incl_mask[incl_aux == lab] = True

    # get rest of numpy arrays
    ndist = ndist_nib.get_fdata()
    label = label_nib.get_fdata()

    # get DONE and processing masks
    DONE_mask = label > 0  # this is for using freesurfer wmparc
    proc_mask = np.logical_and(np.logical_and(ndist > 0., ndist < 1.), incl_mask)

    # setup the ouptut vol
    out = np.zeros(label.shape, dtype=label.dtype)

    # initialize labels in cortex
    out[DONE_mask] = label[DONE_mask]  # this is for using freesurfer wmparc

    # start with connectivity 1
    its_conn = 1

    # main loop
    while not np.all(DONE_mask[proc_mask]):

        if verbose:
            print('%0.1f done' % (100. * float(DONE_mask[proc_mask].sum()) / float(proc_mask.sum())))

        # loop to increase connectivity for non-reachable TO-DO points
        while True:

            # dilate the SOLVED area
            aux = binary_dilation(DONE_mask, iterate_structure(connectivity, its_conn))
            # next TO-DO: close to DONE, in the processing mask and not yet done
            TODO_mask = np.logical_and(np.logical_and(aux, proc_mask), np.logical_not(DONE_mask))

            if TODO_mask.sum() > 0:
                break

            if verbose:
                print('Non-reachable points. Increasing connectivity')

            its_conn += 1

        # sort TO-DO points by ndist
        Idx_TODO = np.argwhere(TODO_mask)
        Idx_ravel = np.ravel_multi_index(Idx_TODO.T, label.shape)
        I_sort = np.argsort(ndist.ravel()[Idx_ravel])

        # iterate along TO-DO points
        for idx in Idx_TODO[I_sort[::-1]]:

            max_dist = -1.

            # process each neighbor
            for off in np.argwhere(iterate_structure(connectivity, its_conn)) - its_conn:

                try:

                    # if it is not DONE then skip
                    if not DONE_mask[idx[0] + off[0], idx[1] + off[1], idx[2] + off[2]]:
                        continue

                    # if it is the largest distance (ie, largest gradient)
                    cur_dist = ndist[idx[0] + off[0], idx[1] + off[1], idx[2] + off[2]]
                    if cur_dist > max_dist:
                        out[idx[0], idx[1], idx[2]] = out[idx[0] + off[0], idx[1] + off[1], idx[2] + off[2]]
                        max_dist = cur_dist

                except:
                    print('something wrong with neighbor at: (%d, %d, %d)' % (
                    idx[0] + off[0], idx[1] + off[1], idx[2] + off[2]))
                    pass

            if max_dist < 0.: print("something went wrong with point: (%d, %d, %d)" % (idx[0], idx[1], idx[2]))

            # mark as solved and remove from visited
            DONE_mask[idx[0], idx[1], idx[2]] = True

    # # remove labels from cortex (old aparc version)
    # out[dest_mask] = 0

    print('Writing output labelmap')
    out_nib = nib.Nifti1Image(out.astype(np.int16), label_nib.affine, label_nib.header)
    nib.save(out_nib, 'wmparc.nii.gz')

    return os.path.abspath('wmparc.nii.gz')


class Annot2LabelInputSpec(CommandLineInputSpec):
    subject = traits.String(desc='subject id', argstr='--subject %s', position=0, mandatory=True)
    hemi = traits.Enum("rh", "lh", desc="hemisphere [rh | lh]", position=1, argstr="--hemi %s", mandatory=True)
    lobes = traits.Enum("lobes", desc='lobes type', argstr='--lobesStrict %s', position=2)
    in_annot = traits.File(desc='input annotation file', exists=True)

class Annot2LabelOutputSpec(TraitedSpec):
    out_annot_file = File(desc = "lobes annotation file", exists = True)

class Annot2Label(CommandLine):
    """wrapper for FreeSurfer command-line tool 'mri_annotation2label'"""
    input_spec = Annot2LabelInputSpec
    output_spec = Annot2LabelOutputSpec
    _cmd = os.path.join(os.environ['FREESURFER_HOME'], 'bin', 'mri_annotation2label')

    def _list_outputs(self):
            outputs = self.output_spec().get()
            outputs['out_annot_file'] = os.path.join(os.path.dirname(self.inputs.in_annot), self.inputs.hemi + ".lobes.annot")
            return outputs

    def _format_arg(self, name, spec, value):
        if(name=='subject'):
             # take only the last part of the subject path
             return spec.argstr % ( os.path.basename(os.path.normpath(self.inputs.subject)))

        return super(Annot2Label, self)._format_arg(name, spec, value)


class Aparc2AsegInputSpec(CommandLineInputSpec):
    subject = traits.String(desc='subject id', argstr='--s %s', position=0, mandatory=True)
    annot = traits.String(desc='name of annot file', argstr='--annot %s', position=1, mandatory=True)
    labelwm = traits.Bool(desc='percolate white matter', argstr='--labelwm', position=2)
    dmax = traits.Int(desc='depth to percolate', argstr='--wmparc-dmax %d', position=3)
    rip = traits.Bool(desc='rip unknown label', argstr='--rip-unknown', position=4)
    hypo = traits.Bool(desc='hypointensities as wm', argstr='--hypo-as-wm', position=5)
    out_file = traits.File(desc='output aseg file', argstr='--o %s', position=6)
    in_lobes_rh = traits.File(desc='input lobar file RH', exists=True)
    in_lobes_lh = traits.File(desc='input lobar file LH', exists=True)

class Aparc2AsegOutputSpec(TraitedSpec):
    out_file = File(desc = "lobes aseg file", exists = True)

class Aparc2Aseg(CommandLine):
    """wrapper for FreeSurfer command-line tool 'mri_aparc2aseg'"""
    input_spec = Aparc2AsegInputSpec
    output_spec = Aparc2AsegOutputSpec

    _cmd = os.path.join(os.environ['FREESURFER_HOME'], 'bin', 'mri_aparc2aseg')

    def _list_outputs(self):
            outputs = self.output_spec().get()
            outputs['out_file'] = os.path.abspath(self.inputs.out_file)
            return outputs

    def _format_arg(self, name, spec, value):
        if(name=='subject'):
             # take only the last part of the subject path
             return spec.argstr % ( os.path.basename(os.path.normpath(self.inputs.subject)))

        return super(Aparc2Aseg, self)._format_arg(name, spec, value)


