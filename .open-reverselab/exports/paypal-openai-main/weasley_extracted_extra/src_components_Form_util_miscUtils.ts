import { appStore, dispatchFormAction } from '@/store';
import { features, getContentHash, getLocale, logger } from '@/lib';
// Untyped imports
import {
  getDateOfBirthOrder,
  getDateOfBirthSeparator,
  padLeft,
  parseByDateOfBirthSeparator, // @ts-expect-error untyped-import
} from '@checkout/react-components';
import type { GenericObjectType } from '@/types';
import type { FormAddressTypes, FormState } from '@/store/models/form/types';
import { getNationalityBasedKycValue } from '@/lib/features/utils';

/* === Begin Types === */
type DateObj = {
  day: string;
  month: string;
  year: string;
};
/* === End Types === */
/**
 * @function stringToDateObject
 * @param {string} dateString date in form of string (ex. '1/12/1990')
 * @returns {object} returns object with string fields year, month, day
 * @description used in serializeFormData since dateOfBirth is stored as string
 *  but graphQL expects type DateOfBirth (object with fields year, month, day)
 */
const stringToDateObject = (dateString: string): DateObj => {
  const { dateMeta } = appStore.getState().api.griffinMetadata;
  const datePattern = dateMeta.datePattern;
  const separator = getDateOfBirthSeparator(datePattern);
  const dateOrder = getDateOfBirthOrder(datePattern, separator);
  const { day, month, year } = parseByDateOfBirthSeparator(
    dateOrder,
    dateString,
    separator,
  );

  // xobuyer requires a 2 digit day and month
  return {
    day: padLeft(day, 2, '0'),
    month: padLeft(month, 2, '0'),
    year,
  };
};

const getPomaFlowData = (): { contentIdentifier: string } => {
  const { country, language, locale } = getLocale();
  const contentHash = getContentHash(locale);
  const pomaTermsVersion = 'terms.pomaTerms';

  // Hardcoded value at end identifies the content key that user agreed to
  const contentIdentifier = `${country}:${language}:${contentHash}:${pomaTermsVersion}`;

  return {
    contentIdentifier,
  };
};

const legalAgreementsFunctionMap = {
  userAgreement: () => {
    let result = null;
    const { majorVersion, minorVersion } =
      appStore.getState().api.userAgreement || {};

    const shouldSendUserAgreement = Boolean(majorVersion && minorVersion);

    if (shouldSendUserAgreement) {
      result = {
        userAgreement: {
          majorVersion,
          minorVersion,
        },
      };
    }

    logger.info(
      `send_legal_agreements_user_agreement_${shouldSendUserAgreement}`,
    );
    return result;
  },
};

// TODO: Improve typing on this object
const getLegalAgreementsData = (): GenericObjectType => {
  const keys = Object.keys(
    legalAgreementsFunctionMap,
  ) as (keyof typeof legalAgreementsFunctionMap)[];
  const legalAgreements = keys
    .map(key => legalAgreementsFunctionMap[key]())
    .reduce((previous, current) => {
      if (current) {
        return { ...previous, ...current };
      }
      return previous;
    }, {});

  return { legalAgreements };
};

/**
 * @function getIsSignupIncentiveOptIn
 * @param {object} data raw installment data fetched from the server
 * @returns {object} Returns the object if isSignupIncentiveOptIn
 *
 */
const getIsSignupIncentiveOptIn = (
  data: FormState,
): { isSignupIncentiveOptIn?: boolean } => {
  if (data.isSignupIncentiveOptIn) {
    return { isSignupIncentiveOptIn: data.isSignupIncentiveOptIn };
  }
  return {};
};

type KycNationalityOnChangeParams = {
  nationality: string;
  addressType?: FormAddressTypes;
};

// TODO: AddressType is probably not needed here. Will re-examine in the future
// This is only ever called when field === nationality which is not
// considered an address field
const kycNationalityOnChange = ({
  nationality,
  addressType,
}: KycNationalityOnChangeParams): void => {
  if (features.config.kycUsesNationalityOnChange) {
    const { form: formState } = appStore.getState();
    const { identityDocumentType } = formState;
    const kycIdTypes = getNationalityBasedKycValue(
      features.config.kycIdTypes,
      nationality,
    );

    const payload = { ...identityDocumentType, value: kycIdTypes[0] };
    dispatchFormAction({
      field: 'identityDocumentType',
      payload,
    });
  }
};

export const stripAddressPrefix = (id: string): string => {
  const addressRegex = /^(billing|shipping|residential)(\w)/;
  return id.replace(addressRegex, (_, __, l) => l.toLowerCase());
};

export {
  getIsSignupIncentiveOptIn,
  getLegalAgreementsData,
  getPomaFlowData,
  kycNationalityOnChange,
  stringToDateObject,
};
