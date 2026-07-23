// Internal Modules
import { features, getContentHash, getLocale } from '@/lib';
import type { CrsFieldResults, DefaultInputState } from '@/store';
import { appStore } from '@/store';
import type { FormState } from '@/store/models/form/types';
import { stringToDateObject } from './miscUtils';
import { CRS_TAXPAYERID_OPTIONS } from '@/components/CRSFields/constants';
import type { CrsNoTaxpayerIdReasons } from '@/components/CRSFields/utils';
import { getCrsNoTaxpayerIdReasons } from '@/components/CRSFields/utils';
import type { GenericObjectType } from '@/types';
import type { CardPayload } from './types';
import { isEligibleForCRS } from './crsUtils';
// Untyped imports
// @ts-expect-error untyped-import
import { formatExpiryForBackend } from '@checkout/react-components';
import { logStretchRewardsAttachedToFpti } from '@/components/Form/fpti';

/* === Begin Types === */
type BankPayload = {
  accountNumber?: string;
  routingNumber?: string;
  iban?: string;
};
type CrsTaxDetails = {
  countryCode: string;
  noTaxPayerIdReason?: string;
  taxPayerIdValue?: string;
};
type CrsPayload = {
  firstName?: string;
  lastName?: string;
  subjectToTaxOutsideLegalCountry: boolean;
  taxDetails?: CrsTaxDetails[];
};
/* === End Types === */

/**
 * @function getCardPayload
 * @param {object} data Form fields that have been filtered based on the flow
 * @returns {object} Returns the formatted graphql variables payload
 * for card.
 */
const getCardPayload = (data: FormState): CardPayload | undefined => {
  const { ui: uiState } = appStore.getState();
  const { fiType } = uiState;

  if (fiType !== 'card') {
    return;
  }

  const {
    cardCvv: { value: cardCvv } = {},
    cardExpiry: { value: cardExpiry } = {},
    cardNumber: { value: cardNumber, cardType },
    currencyConversionSelection: currencyConversionType,
    cardProductClass: { value: productClass } = {},
  } = data;

  return {
    card: {
      cardNumber,
      ...(cardExpiry && { expirationDate: formatExpiryForBackend(cardExpiry) }),
      ...(cardCvv && { securityCode: cardCvv }),
      ...(cardType && { type: cardType }),
      ...(features.isActive('shouldCollectCardProductClass') && {
        productClass,
      }),
    },
    ...(currencyConversionType && { currencyConversionType }),
  };
};

/**
 * @function getSignupData
 * @param {object} formData
 * @returns {object}
 * @description Serializes the form data that is specific to the signup flow
 */
const getSignupData = (
  formData: FormState,
): Partial<FormState> & {
  contentIdentifier: string;
  marketingOptOut: boolean;
} => {
  const {
    marketingOptIn: { value: marketingOptIn },
  } = formData;
  const password = formData?.password?.value as unknown as DefaultInputState;
  const { country, language, locale } = getLocale();
  const contentHash = getContentHash(locale);
  const isPasswordlessUpgrade = features.isActive('isPasswordlessUpgrade');

  // Hardcoded value at end identifies the content key that user agreed to
  // prettier-ignore
  const contentIdentifier =
    `${country}:${language}:${contentHash}:compliance.signupTerms`;

  // Know Your Customer fields -- different countries require different
  // information to be collected. Examples - DOB, Nationality, Occupation, etc.
  // Filtering out identityDocumentNumber because we can combine the object in
  // the following reduce on identityDocumentType
  const kycFields = features.config.kycFields
    .filter(
      (field: string) =>
        field !== 'IdentityDocumentNumber' &&
        field !== 'SecondaryIdentityDocumentNumber',
    )
    .reduce((accum: GenericObjectType, field: keyof FormState) => {
      const formattedField = (field[0].toLowerCase() +
        field.substring(1)) as keyof FormState;
      switch (formattedField) {
        case 'dateOfBirth': {
          const { value: dobString } =
            formData.dateOfBirth as DefaultInputState;
          const dateObject = stringToDateObject(dobString);
          return {
            ...accum,
            dateOfBirth: dateObject,
          };
        }
        case 'identityDocumentType': {
          const { value: identityDocumentType } =
            formData.identityDocumentType as DefaultInputState;
          const { value: identityDocumentNumber } =
            formData.identityDocumentNumber as DefaultInputState;

          return {
            ...accum,
            identityDocument: {
              type: identityDocumentType,
              value: identityDocumentNumber,
            },
          };
        }
        case 'secondaryIdentityDocumentType': {
          // We only send secondaryIdentityDocument if
          // countryOfResidence is Russia
          if (formData.countryOfResidence?.value !== 'RU') {
            break;
          }

          const { value: secondaryIdentityDocumentType } =
            formData.secondaryIdentityDocumentType as DefaultInputState;
          const { value: secondaryIdentityDocumentNumber } =
            formData.secondaryIdentityDocumentNumber as DefaultInputState;

          return {
            ...accum,
            secondaryIdentityDocument: {
              type: secondaryIdentityDocumentType,
              value: secondaryIdentityDocumentNumber,
            },
          };
        }
        default: {
          return {
            ...accum,
            [formattedField]: (formData[formattedField] as DefaultInputState)
              ?.value,
          };
        }
      }
    }, {}) as Partial<FormState>;

  return {
    contentIdentifier,
    // xobuyer uses `marketingOptOut` because it requires an extra service call
    // after signup to opt out. The client calls it opt in because it's an
    // optional field the user has to explicitly check off.
    marketingOptOut: !marketingOptIn,
    ...(!isPasswordlessUpgrade && {
      password,
    }),
    ...kycFields,
  };
};

/**
 * @function getBankPayload
 * @param {object} data Form fields that have been filtered based on the flow
 * @returns {object} Returns the formatted graphql variables payload
 * for bank.
 */
const getBankPayload = (data: FormState): { bank: BankPayload } | undefined => {
  const { ui: uiState } = appStore.getState();
  const { fiType } = uiState;

  if (fiType !== 'bank') {
    return;
  }

  const {
    bankAccountNumber,
    bankAccountType: { value: bankAccountType },
    bankIban,
    bankSortCode,
  } = data;

  const bankPayload: BankPayload = {};
  if (bankAccountType === 'bank') {
    bankPayload.accountNumber = bankAccountNumber.value;
    bankPayload.routingNumber = bankSortCode.value;
  } else {
    bankPayload.iban = bankIban.value;
  }

  return {
    bank: {
      ...bankPayload,
    },
  };
};

/**
 * Helper function used to get crs tax details
 */
const getCrsTaxDetails = ({
  countryCode,
  taxPayerIdValue,
  noTaxPayerIdReason,
  taxPayerIdType,
}: CrsFieldResults): CrsTaxDetails => {
  const crsNoTaxIdReasons = getCrsNoTaxpayerIdReasons();

  let taxPayerIdValueResult = null;
  let noTaxPayerIdReasonResult = null;

  if (taxPayerIdType === CRS_TAXPAYERID_OPTIONS.NO_TAXPAYER_ID) {
    noTaxPayerIdReasonResult =
      crsNoTaxIdReasons[
        noTaxPayerIdReason.value as keyof CrsNoTaxpayerIdReasons
      ];
  } else {
    taxPayerIdValueResult = taxPayerIdValue.value;
  }

  return {
    countryCode: countryCode.value,
    ...(noTaxPayerIdReasonResult && {
      noTaxPayerIdReason: noTaxPayerIdReasonResult,
    }),
    ...(taxPayerIdValueResult && {
      taxPayerIdValue: taxPayerIdValueResult,
    }),
  };
};

/**
 * @function getCrsPayload
 * @param {object} formState
 * @returns {object}
 * @description Returns the formatted graphql variables payload
 * for crsData.
 */

const getCrsPayload = (
  formState: FormState,
): { crsData: CrsPayload | null } => {
  let crsData = null;

  if (isEligibleForCRS()) {
    const { firstName, lastName, crsTaxDetails } = formState;

    const onboardingCountry = getLocale().country;

    const subjectToTaxOutsideLegalCountry =
      crsTaxDetails?.value?.some(
        taxDetail =>
          taxDetail.countryCode.value &&
          taxDetail.countryCode.value !== onboardingCountry,
      ) || false;

    const taxDetails = crsTaxDetails?.value.map(taxDetails =>
      getCrsTaxDetails(taxDetails),
    );

    crsData = {
      firstName: firstName?.value,
      lastName: lastName?.value,
      subjectToTaxOutsideLegalCountry,
      taxDetails,
    };
  }

  return {
    crsData,
  };
};

const getStretchRewardData = (): boolean => {
  const isExpandedStretchRewards = features.isActive(
    'isExpandedStretchRewards',
  );
  logStretchRewardsAttachedToFpti(isExpandedStretchRewards);
  return isExpandedStretchRewards;
};

export {
  getBankPayload,
  getCardPayload,
  getCrsPayload,
  getSignupData,
  getStretchRewardData,
};
