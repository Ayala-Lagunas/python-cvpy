#!/usr/bin/env python
# encoding: utf-8
#
# Copyright SAS Institute
#
#  Licensed under the Apache License, Version 2.0 (the License);
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.
#

''' BioMedImage analysis tools '''

import sys
import struct
import numpy as np
from typing import List
from warnings import warn
from swat import CAS, CASTable
from cvpy.base.ImageTable import ImageTable
from cvpy.biomedimage.LabelConnectivity import LabelConnectivity
from enum import *


class BiomedImage(object):
    """
    Implement biomedical image processing functions.

     Parameters
     ----------
     cas_session
          Specifies the CAS session.

     Returns
     -------
     :class:`BiomedImage`
    """

    def __init__(self, cas_session: CAS = None) -> None:
        self._cas_session = cas_session
        # Load the actionsets
        self._cas_session.loadactionset('image')
        self._cas_session.loadactionset('biomedimage')
        self._cas_session.loadactionset('fedsql')

    @property
    def cas_session(self) -> CAS:
        return self._cas_session

    @cas_session.setter
    def cas_session(self, cas_session) -> None:
        self._cas_session = cas_session

    def quantify_sphericity(self, image_table: ImageTable, use_spacing: bool, input_background: float,
                            label_connectivity: LabelConnectivity, sphericity: CASTable) -> None:
        """
        Quantify the sphericity for the given component from a CAS table.

        Parameters
        ----------
        image_table: ImageTable
             Specifies the CAS table that contains the image binaries.
        use_spacing: bool
             When set to True, use image spacing in the sphericity calculation.
        input_background: float
             Specifies the background value in input images.
        label_connectivity: LabelConnectivity.FACE | LabelConnectivity.VERTEX
             Specifies the level of connectivity for connected components: LabelConnectivity.FACE or LabelConnectivity.VERTEX
        sphericity: CASTable
             Specifies the output CAS table.

        Examples
        --------
        >>> # Import classes
        >>> from swat import CAS
        >>> from cvpy.base.ImageTable import ImageTable
        >>> from cvpy.biomedimage.BiomedImage import BiomedImage
        >>> from cvpy.biomedimage.LabelConnectivity import LabelConnectivity
        >>> ## Connect to CAS
        >>> s = swat.CAS("example.com", 5570)
        >>> # Construct Biomed object
        >>> biomed = BiomedImage(s)
        >>> # Construct tables that are parameters to the quantify_sphericity API
        >>> image_table = s.CASTable(...)
        >>> input_table = ImageTable(image_table)
        >>> output_table = s.CASTable(...)
        >>> # Call the API
        >>> BiomedImage.quantify_sphericity(input_table.table,...,output_table)

        """
        conn = self._cas_session

        # Quantify the volume and perimeter of the given component.
        conn.biomedimage.quantifybiomedimages(images=dict(table=image_table.table),
                                              copyvars=['_path_'],
                                              region='COMPONENT',
                                              quantities=[dict(quantityparameters=dict(quantitytype='perimeter')),
                                                          dict(quantityparameters=dict(quantitytype='content',
                                                                                       useSpacing=use_spacing))
                                                          ],
                                              labelparameters=dict(labelType='basic',
                                                                   connectivity=label_connectivity.name),
                                              inputbackground=input_background,
                                              casout=dict(name='quantify'),
                                              )

        # Compute sphericity based on perimeter and volume of the lesion
        conn.fedsql.execdirect(f'''
            create table {sphericity.name} as 
            select _path_,_perimeter_,_content_, (power(pi(), 1.0/3.0) * power(6*_content_, 2.0/3.0))/_perimeter_ as 
            sphericity from quantify
            ''')

        # Delete the quantify table
        conn.table.dropTable(name='quantify')

    def mask_image(self, image: ImageTable, mask: ImageTable, casout: CASTable,
                   input_background: int = 0, decode: bool = False, output_background: int = 0,
                   add_columns: list(Enum) = None, copy_vars: list(Enum) = None):
        """
        Applies masking to an ImageTable.
        Parameters
        ------------
        image : :class:`cvpy.ImageTable`
            Specifies the input image table to be masked.
        mask : :class:`cvpy.ImageTable`
            Specifies the image table that will be used for masking.
        input_background : :class:`int`
            Specifies the pixel intensity of the input image background.
        casout : :class:`swat.CASTable`
            Specifies the output image table.
        decode : :class:`bool`
            Specifies whether to decode the output image table.
        output_background : :class:`int`
            Specifies the pixel intensity of the output image background.
        add_columns : :class:`list[enum.Enum]`
            Specifies the metadata columns to be added to the output image table.
        copy_vars : :class:`list[enum.Enum]`
            Specifies which columns to copy to the output image table.

        Returns
        ------------
        None
        """

        conn = self._cas_session

        ###############################################
        ########### Mask Tbl Decoded ##################
        ###############################################
        if mask.has_decoded_images():

            # List of columns that will be alternated
            alter_columns = [dict(name=mask.image, rename="seg"),
                             dict(name=mask.dimension, rename="dim"),
                             dict(name=mask.resolution, rename="res"),
                             dict(name=mask.imageFormat, rename="form")]

            # SQL string to create the mask table
            fed_sql_str = f'''create table _images_to_mask_ as 
                select a.seg, a.dim, a.res, a.form, b.* 
                from {mask.table.name} as a inner join {image.table.name} as b 
                on a._id_=b._id_'''

            # Dictionary for specifying information in our binary operation
            binary_operation_dict = dict(binaryoperationtype="mask_specific",
                                         image="seg",
                                         dimension="dim",
                                         resolution="res",
                                         imageformat="form",
                                         outputBackground=output_background,
                                         inputBackground=input_background)

            # Mini method for renaming columns in ImageTable object
            # *This step must be completed AFTER the alter table command*
            def rename_columns():
                mask.image = "seg"
                mask.dimension = "dim"
                mask.resolution = "res"
                mask.imageFormat = "form"

        ###############################################
        ############# Mask Tbl Encoded ################
        ###############################################
        else:

            # List of columns that will be alternated
            alter_columns = [dict(name=mask.image, rename="seg")]

            # SQL string to create the mask table
            fed_sql_str = f'''create table _images_to_mask_ as 
                select a.seg, b.* 
                from {mask.table.name} as a inner join {image.table.name} as b 
                on a._id_=b._id_'''

            # Dictionary for specifying information in our binary operation
            binary_operation_dict = dict(binaryoperationtype="mask_specific",
                                         image="seg",
                                         outputBackground=output_background,
                                         inputBackground=input_background)

            # Mini method for renaming columns in ImageTable Object
            # *This step must be completed AFTER the alter table command*
            def rename_columns():
                mask.image = "seg"

        ###############################################
        ############### Masking Step ##################
        ###############################################

        # Change column names so that we can merge tables
        conn.table.altertable(name=mask.table, columns=alter_columns)

        # Create Images to Mask Table
        _images_to_mask_ = conn.CASTable("_images_to_mask_")

        # SQL Statement to join tables
        conn.fedsql.execdirect(fed_sql_str)

        # Masking step
        conn.biomedimage.processbiomedimages(
            images=dict(table=_images_to_mask_),
            steps=[dict(stepparameters=dict(steptype="binary_operation",
                                            binaryoperation=binary_operation_dict)
                        )],
            decode=decode,
            addcolumns=add_columns,
            casout=casout,
            copyvars=copy_vars
        )

        # Delete our temporary table
        conn.table.dropTable(_images_to_mask_)

        # Change column names in the ImageTable
        rename_columns()
