from __future__ import print_function
import os
import re
import itertools
import numpy as np
from ._population import Population
from pychemia import pcm_log
from pychemia.code.abinit import InputVariables
from pychemia.utils.mathematics import gram_smith_qr


class OrbitalDFTU(Population):

    def __init__(self, name, num_electrons_spin, connections, abinit_input='abinit.in'):

        """
        Creates a population of ABINIT inputs, the candidates have the same structure and
        uses the same input variables with exception of dmatpawu, the purpose of the
        population is to use global-population searchers to find the correlation matrices
        'dmatpawu' that minimizes the energy.

        :param name: The name of the 'PyChemiaDB' database created to stored the different
                        set of variables and the resulting output from abinit.
                     When using databases protected with username and password, the database
                        should be created independently and the database object must be use
                        as the 'name' argument

        :param abinit_input: The abinit input file, all the variables will be preserve for all new candidates, except
                        for 'dmatpawu' the only variable that changes.

        :param num_electrons_spin: Number of electrons for each atom where U is applied. They number of elements must
                        be equal to the number of matrices defined on dmatpawu and they correspond to the number of
                        electrons for the spin channel associated with the matrix defined on dmatpawu. Notice that
                        several cases uses different number of matrices on 'dmatpawu' and their spin definition changes.
                        The code currently is not checking the correctness of the numbers you enter here.
        :param connections: The occupation matrices could be related between different atoms. The connection array
                        defines which matrices are identical and their identity is enforced when new random 'dmatpawu'
                        is created or changed.
        """
        # Call the parent class initializer to link the PychemiaDB that will be used
        Population.__init__(self, name, 'global')
        # Checking for existence of 'abinit.in'
        if not os.path.isfile(abinit_input):
            print("Abinit input not found")
            raise ValueError
        # Reading the input variables and getting the structure
        self.input = InputVariables(abinit_input)
        self.structure = self.input.get_structure()

        # Computing the orbital that will be corrected
        # 2 (d-orbitals) or 3 (f-orbitals)
        self.maxlpawu = max(self.input.get_value('lpawu'))

        # natpawu is computed from the values of spinat
        spinat = self.input.get_value('spinat')
        if spinat is None:
            print('I could not determine the number of atoms playing a role in the DFT+U calculation')
            raise ValueError('Could not determine natpawu')
        else:
            spinat = np.array(spinat).reshape((-1, 3))
            self.natpawu = np.sum(np.apply_along_axis(np.linalg.norm, 1, spinat) != 0)

        # nsppol is the number of independent spin polarisations. Can take the values 1 or 2
        if self.input.has_variable('nsppol'):
            self.nsppol = self.input.get_value('nsppol')
        else:
            # Default from ABINIT
            self.nsppol = 1

        # nspinor it the umber of spinorial components of the wavefunctions
        if self.input.has_variable('nspinor'):
            self.nspinor = self.input.get_value('nspinor')
        else:
            self.nspinor = 1

        # nspden is the number of spin-density components
        if self.input.has_variable('nspden'):
            self.nspden = self.input.get_value('nspden')
        else:
            self.nspden = self.nsppol

        if self.nsppol == 1 and self.nspinor == 1 and self.nspden == 1:
            # Non-magnetic system (nsppol=1, nspinor=1, nspden=1):
            # One (2lpawu+1)x(2lpawu+1) dmatpawu matrix is given for each atom on which +U is applied.
            # It contains the "spin-up" occupations.
            self.nmatrices = self.natpawu
        elif self.nsppol == 2 and self.nspinor == 1 and self.nspden == 2:
            # Ferromagnetic spin-polarized (collinear) system (nsppol=2, nspinor=1, nspden=2):
            # Two (2lpawu+1)x(2lpawu+1) dmatpawu matrices are given for each atom on which +U is applied.
            # They contain the "spin-up" and "spin-down" occupations.
            self.nmatrices = 2*self.natpawu
        elif self.nsppol == 1 and self.nspinor == 1 and self.nspden == 2:
            # Anti-ferromagnetic spin-polarized(collinear) system(nsppol=1, nspinor=1, nspden=2):
            # One(2lpawu + 1)x(2lpawu + 1) dmatpawu matrix is given for each atom on which +U is applied.
            # It contains the "spin-up" occupations.
            self.nmatrices = self.natpawu
        elif self.nsppol == 1 and self.nspinor == 2 and self.nspden == 4:
            # Non-collinear magnetic system (nsppol=1, nspinor=2, nspden=4):
            # Two (2lpawu+1)x(2lpawu+1) dmatpawu matrices are given for each atom on which +U is applied.
            # They contains the "spin-up" and "spin-down" occupations (defined as n_up=(n+|m|)/2 and n_dn=(n-|m|)/2),
            #    where m is the integrated magnetization vector).
            self.nmatrices = 2*self.natpawu
        elif self.nsppol == 1 and self.nspinor == 2 and self.nspden == 1:
            # Non-collinear magnetic system with zero magnetization (nsppol=1, nspinor=2, nspden=1):
            # Two (2lpawu+1)x(2lpawu+1) dmatpawu matrices are given for each atom on which +U is applied.
            # They contain the "spin-up" and "spin-down" occupations;
            self.nmatrices = 2*self.natpawu

        self.num_electrons_spin = list(num_electrons_spin)
        if len(self.num_electrons_spin) != self.nmatrices:
            raise ValueError('Number of electrons on each spin channel is not consistent with the number of matrices '
                             'defined on dmatpawu')

        self.connections = list(connections)
        if len(self.num_electrons_spin) != self.nmatrices:
            raise ValueError('Number of connections between matrices is not consistent with the number of matrices '
                             'defined on dmatpawu')

    def __str__(self):
        ret = ' Population LDA+U\n\n'
        ret += ' Name:               %s\n' % self.name
        ret += ' Tag:                %s\n' % self.tag
        ret += ' Formula:            %s\n' % self.structure.formula
        ret += ' natpawu:            %d\n' % self.natpawu
        ret += ' connections:        %s\n' % self.connections
        ret += ' num_electrons_spin: %s\n' % self.num_electrons_spin

        ret += ' Members:            %d\n' % len(self.members)
        ret += ' Actives:            %d\n' % len(self.actives)
        ret += ' Evaluated:          %d\n' % len(self.evaluated)
        return ret

    @property
    def ndim(self):
        """
        Dimension of the matrices defined on dmatpawu, for 'd' orbitals is 5 for 'f' orbitals is 7

        :return:
        """
        return 2 * self.maxlpawu + 1

    def add_random(self):
        """
        Creates a new set of variables to reconstruct the dmatpawu

        matrix_i (integers) is a matrix natpawu x ndim with entries are 0 or 1
        matrix_d (deltas) is a matrix natpawu x ndim with entries are [0, 0.5)
        P (matrices) is a set of matrices natpawu x ndim x ndim
        Those three matrices allow to reconstruct the variable 'dmatpawu' used by ABINIT

        :return:
        """
        matrices_defined = []

        matrix_i = self.nmatrices*[None]
        matrix_d = self.nmatrices*[None]
        eigvec = self.nmatrices*[None]

        for i in range(self.nmatrices):

            if self.connections[i] not in matrices_defined:
                matrix_i = np.zeros((self.natpawu, self.ndim), dtype=int)
                matrix_d = np.zeros((self.natpawu, self.ndim))
                eigvec = np.zeros((self.natpawu, self.ndim, self.ndim))
                nelect = self.num_electrons_spin[i]

                val = [x for x in list(itertools.product(range(2), repeat=self.ndim)) if sum(x) == nelect]
                ii = val[np.random.randint(len(val))]
                dd = np.zeros(self.ndim)
                matrix_i[i] = list(ii.flatten())
                matrix_d[i] = list(dd.flatten())
                matrices_defined.append(self.connections[i])
                p = gram_smith_qr(self.ndim)
                eigvec[i] = list(p.flatten())

            else:
                # Search the connection and use it to fill the matrices
                index = self.connections.index(self.connections[i])
                matrix_i[i] = matrix_i[index]
                matrix_d[i] = matrix_d[index]
                eigvec[i] = eigvec[index]

        data = {'R': eigvec, 'O': matrix_i, 'D': matrix_d}

        return self.new_entry(data), None

    def cross(self, ids):
        """
        Crossing algorithm used notably by GA to mix the information from several candidates
        Not implemented

        :param ids:
        :return:
        """
        pass

    def evaluate_entry(self, entry_id):
        """
        Evaluation externalized, no implemented

        :param entry_id:
        :return:
        """
        pass

    def from_dict(self, population_dict):
        pass

    def new_entry(self, data, active=True):
        """
        Creates a new entry on the population database from given data.

        :param data: dictionary with 3 keys 'D' for deltas, 'I' for the integers
        and eigen for the rotation matrix applied to the orbitals
        :param active: if True, the entry is enabled on the DB to be evaluated.
        :return:
        """

        properties = {'R': list(data['R'].flatten()),
                      'D': list(data['D'].flatten()),
                      'O': list(data['O'].flatten())}
        status = {self.tag: active}
        entry = {'structure': self.structure.to_dict, 'properties': properties, 'status': status}
        entry_id = self.insert_entry(entry)
        pcm_log.debug('Added new entry: %s with tag=%s: %s' % (str(entry_id), self.tag, str(active)))
        return entry_id

    def is_evaluated(self, entry_id):
        pass

    def check_duplicates(self, ids):
        """
        For a given list of identifiers 'ids' checks the values for the function 'distance' and return a dictionary
          where each key is the identifier of a unique candidate and the value is a list of identifiers considered
          equivalents to it.

        :param ids:  List of identifiers for wich the check will be performed
        :return:
        """
        ret = {}
        for i in range(len(ids)):
            entry_i = self.get_entry(ids[i])
            for j in range(i + 1, len(ids)):
                entry_j = self.get_entry(ids[j])
                if self.distance(ids[i], ids[j]) < 1E-3:
                    if entry_i in ret:
                        ret[entry_i].append(entry_j)
                    else:
                        ret[entry_i] = [entry_j]

    def distance(self, entry_id, entry_jd):
        """
        Measure of distance for two entries with identifiers 'entry_id' and 'entry_jd'
        TODO: The definition must be changed and compare the resulting dmatpawu instead of
        individual components

        :param entry_id: Identifier of first entry
        :param entry_jd: Identifier of second entry
        :return:
        """
        entry_i = self.get_entry(entry_id)
        entry_j = self.get_entry(entry_jd)
        dmat_i = entry_i['properties']['P']
        dmat_j = entry_j['properties']['P']
        dist_p = np.linalg.norm(dmat_j - dmat_i)
        dmat_i = entry_i['properties']['d']
        dmat_j = entry_j['properties']['d']
        dist_d = np.linalg.norm(dmat_j - dmat_i)
        return dist_d + dist_p

    def move_random(self, entry_id, factor=0.2, in_place=False, kind='move'):
        """
        Move one candidate with identifier 'entry_id' randomly with a factor
        given by 'factor'

        :param entry_id: Identifier of entry
        :param factor: Factor use to scale the randomness of change
        :param in_place: If True the candidate is changed keeping the identifier unchanged
        :param kind: Use when several algorithms are used for movement. One implemented here
        :return:
        """
        pass
        # entry_i = self.get_entry(entry_id)
        # dmat_i = entry_i['properties']['dmatpawu']
        # dmat_i += factor*np.random.random_sample(len(dmat_i))
        # self.pcdb.db.pychemia_entries.update({'_id': entry_id}, {'$set': {'properties.dmatpawu': list(dmat_i)}})

    def move(self, entry_id, entry_jd, factor=0.2, in_place=False):
        """
        Move one candidate with identifier 'entry_id' in the direction of another candidate 'entry_jd'

        :param entry_id: Identifier of first entry (Origin)
        :param entry_jd: Identifier of second entry (Target)
        :param factor: Scale factor for change, 0 scale is the 'Origin' candidate, 1 is the 'Target' candidate
                        Intermediate values will change candidates accordingly
        :param in_place: If True the candidate is changed keeping the identifier unchanged
        :return:
        """
        entry_i = self.get_entry(entry_id)
        dmat_i = np.array(entry_i['properties']['P'])
        entry_j = self.get_entry(entry_jd)
        dmat_j = np.array(entry_j['properties']['P'])
        dmat_i += factor * (dmat_j - dmat_i)

    def recover(self):
        pass

    def value(self, entry_id):
        pass

    def str_entry(self, entry_id):
        entry = self.get_entry(entry_id)
        print(entry['properties']['P'], entry['properties']['d'])

    def get_duplicates(self, ids):
        return None


def params_reshaped(params, ndim):
    """
    Reorder and reshape the contents of the dictionary 'params' and prepare the matrices
    to build a consistent dmatpawu variable.

    :param params:
    :param ndim:
    :return:
    """
    matrix_o = np.array(params['O'], dtype=int).reshape((-1, ndim))
    matrix_d = np.array(params['D']).reshape((-1, ndim))
    matrix_r = np.array(params['R']).reshape((-1, ndim, ndim))
    return matrix_o, matrix_d, matrix_r


def params2dmatpawu(params, ndim):
    """
    Build the variable dmatpawu from the components stored in params

    :param params: dictionary with keys 'I', 'D' and 'eigen'
    :param ndim: dimension of the correlation matrix
                5 for 'd' orbitals, 7 for 'f' orbitals
    :return:
    """
    matrix_o, ddd, eigvec = params_reshaped(params, ndim)

    eigval = np.array(iii, dtype=float)
    for i in range(len(eigval)):
        for j in range(ndim):
            if iii[i, j] == 0:
                eigval[i, j] += ddd[i, j]
            else:
                eigval[i, j] -= ddd[i, j]
    dm = np.zeros((len(eigvec), ndim, ndim))
    for i in range(len(eigvec)):
        dm[i] = np.dot(eigvec[i], np.dot(np.diag(eigval[i]), np.linalg.inv(eigvec[i])))
    return dm


def dmatpawu2params(dmatpawu, ndim):
    """
    Takes the contents of the variable 'dmatpawu' and return their components as a set of occupations 'O', deltas 'D' and
    rotation matrix 'R'.
    The rotation matrix R is ensured to be an element of SO(ndim), ie det(R)=1.
    When the eigenvectors return a matrix with determinant -1 a mirror on the first dimension is applied.
    Such condition has no effect on the physical result of the correlation matrix

    :param dmatpawu: The contents of the variable 'dmatpawu'. A list of number representing N matrices ndim x ndim
    :param ndim: ndim is 5 for 'd' orbitals and 7 for 'f' orbitals
    :return:
    """
    dm = np.array(dmatpawu).reshape((-1, ndim, ndim))
    eigval = np.array([np.linalg.eigh(x)[0] for x in dm])
    matrix_o = np.array(np.round(eigval), dtype=int)
    matrix_d = np.abs(eigval - matrix_o)
    matrix_r = np.array([np.linalg.eigh(x)[1] for x in dm])

    mirror = np.eye(ndim)
    mirror[0,0] = -1

    for i in range(len(matrix_r)):
        if np.linalg.det(matrix_r[i])<0:
            matrix_r[i]= np.dot(matrix_r[i], mirror)

    params = {'O': list(matrix_o.flatten()),
              'D': list(matrix_d.flatten()),
              'R': list(matrix_r.flatten())}
    return params


def get_pattern(params, ndim):
    """

    :param params:
    :param ndim:
    :return:
    """

    eigvec = np.array(params['eigvec']).reshape((-1, ndim, ndim))
    natpawu = len(eigvec)
    connection = np.zeros((natpawu, natpawu, ndim, ndim))

    bb = np.dot(eigvec[0], np.linalg.inv(eigvec[3]))
    # connection = np.array(np.round(np.diagonal(bb)), dtype=int)

    iii = np.array(params['I'], dtype=int).reshape((-1, ndim))

    pattern = np.zeros((natpawu, natpawu))
    for i in range(natpawu):
        for j in range(i, natpawu):

            bb = np.dot(eigvec[0], np.linalg.inv(eigvec[3]))
            connection[i, j] = bb
            connection[j, i] = bb

            if np.all(np.array(iii[i] == iii[j])):
                pattern[i, j] = 1
                pattern[j, i] = 1
            else:
                pattern[i, j] = 0
                pattern[j, i] = 0

    return connection, pattern


def get_final_correlation_matrices_from_output(filename):
    rf = open(filename)
    data = rf.read()
    mainblock = re.findall('LDA\+U DATA[\s\w\d\-\.=,>:]*\n\n\n', data)
    assert len(mainblock)==1

    pattern = """For Atom\s*(\d+), occupations for correlated orbitals. lpawu =\s*([\d]+)\s*Atom\s*[\d]+\s*. Occ. for lpawu and for spin\s*\d+\s*=\s*([\d\.]+)\s*Atom\s*[\d]+\s*. Occ. for lpawu and for spin\s*\d+\s*=\s*([\d\.]+)\s*=> On atom\s*\d+\s*,  local Mag. for lpawu is[\s\d\w\.\-]*== Occupation matrix for correlated orbitals:\s*Occupation matrix for spin  1\s*([\d\.\-\s]*)Occupation matrix for spin  2\s*([\d\.\-\s]*)"""
    ans = re.findall(pattern, mainblock[0])
    print(ans)

    ret=[]
    for i in ans:
        atom_data = {}
        atom_data['atom number'] = int(i[0])
        atom_data['orbital'] = int(i[1])
        atom_data['occ spin 1'] = float(i[2])
        atom_data['occ spin 2'] = float(i[3])
        matrix=[float(x) for x in i[4].split()]
        atom_data['matrix spin 1'] = list(matrix)
        matrix=[float(x) for x in i[5].split()]
        atom_data['matrix spin 2'] = list(matrix)
        ret.append(atom_data)
    return ret


def get_final_dmatpawu(filename):
    ret = get_final_correlation_matrices_from_output(filename)
    dmatpawu = []
    for i in ret:
        dmatpawu += i['matrix spin 1']
    return dmatpawu
